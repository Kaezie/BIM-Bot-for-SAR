/* Reference for the supplied AI-ESP32-CAM RE1.2 / matching Ai-Thinker pin map.
 * Confirm the NEW board's pin map and regulated supply before flashing.
 * Does not modify the original camera, temperature sensor, or motor controller.
 * Compile with Arduino-ESP32; hardware testing required after board confirmation.
 */
#include <WiFi.h>
#include <atomic>
#include "esp_camera.h"
#include "esp_system.h"
#include "esp_http_server.h"
#include "esp_heap_caps.h"
#include "driver/ledc.h"
#include "freertos/semphr.h"
#include "lwip/sockets.h"
#include "illumination_lease.h"
#include "frame_pacing.h"
#include "stream_packet.h"
#include "camera_startup.h"
#include "wifi_retry.h"
#include "thermal_config.h"
#include "thermal_frame.h"
#if BIMBOT_THERMAL_ENABLED
#include "thermal_sensor.h"
#endif
#include "wifi_secrets.h"

#ifndef NIGHTVISION_BOARD_CONFIRMED
#error "Confirm the new camera board and set NIGHTVISION_BOARD_CONFIRMED in wifi_secrets.h."
#endif
#if !CONFIG_IDF_TARGET_ESP32
#error "This pin map and LEDC configuration target the confirmed original ESP32 camera board."
#endif

httpd_handle_t streamServer = nullptr;
httpd_handle_t controlServer = nullptr;
static std::atomic<bool> cameraReady{false};
static CameraStartup cameraStartup;
static WifiRetry wifiRetry;
// Retain platform-default transmit power during the stream-pacing trial.
static std::atomic<bool> streamStagingActive{false};

static SemaphoreHandle_t thermalMutex = nullptr;
static ThermalFrame thermalFrame;
static const char *thermalState = "disabled";

#if BIMBOT_THERMAL_ENABLED
static ThermalSensor thermalSensor;
static float thermalWorkFrame[ThermalFrame::pixels];

static void invalidateThermal(const char *state) {
  xSemaphoreTake(thermalMutex, portMAX_DELAY);
  thermalFrame.invalidate();
  thermalState = state;
  xSemaphoreGive(thermalMutex);
}

static void thermalTask(void *) {
  bool initialized = false;
  uint32_t lastReportAt = 0;
  for (;;) {
    if (!initialized) {
      invalidateThermal("initializing");
      initialized = thermalSensor.begin();
      if (!initialized) {
        invalidateThermal("sensor_unavailable");
        Serial.println("Thermal sensor unavailable. Check power, SDA14/SCL13 and I2C mode with power off.");
        vTaskDelay(pdMS_TO_TICKS(5000));
        continue;
      }
      Serial.println("MLX90640 initialized. Waiting for a complete thermal frame.");
    }
    // Clear both subpages before every acquisition. Never publish old pixels
    // mixed with a failed or incomplete new image.
    for (float &value : thermalWorkFrame) value = NAN;
    const int result = thermalSensor.readFrame(thermalWorkFrame);
    if (result != 0) {
      invalidateThermal("frame_unavailable");
      Serial.printf("Thermal read failed (%d). Video/light remain independent; retrying sensor.\n", result);
      initialized = false;
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }
    const uint32_t now = millis();
    xSemaphoreTake(thermalMutex, portMAX_DELAY);
    const bool published = thermalFrame.publish(thermalWorkFrame, now);
    thermalState = published ? "ready" : "invalid_frame";
    const float minimum = thermalFrame.minimum, maximum = thermalFrame.maximum;
    const uint32_t sequence = thermalFrame.sequence;
    xSemaphoreGive(thermalMutex);
    if (!published) initialized = false;
    if (published && (sequence == 1 || uint32_t(now - lastReportAt) >= 10000)) {
      Serial.printf("Thermal frame %lu: 24x32, scene %.2f to %.2f C.\n",
                    (unsigned long)sequence, double(minimum), double(maximum));
      lastReportAt = now;
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}
#endif

static void prepareThermal() {
#if BIMBOT_THERMAL_ENABLED
  thermalMutex = xSemaphoreCreateMutex();
  thermalState = thermalMutex ? "waiting_for_camera" : "task_unavailable";
#else
  Serial.println("Thermal acquisition disabled. Confirm wiring/power, then enable BIMBOT_THERMAL_ENABLED in thermal_config.h.");
#endif
}

static void startThermal() {
#if BIMBOT_THERMAL_ENABLED
  if (!thermalMutex) return;
  invalidateThermal("initializing");
  // Dedicated, yielding acquisition keeps loop/light leases and HTTP handlers
  // independent of sensor waits. Stack size is bytes in ESP-IDF FreeRTOS.
  if (xTaskCreatePinnedToCore(thermalTask, "thermal", 16384, nullptr, 1, nullptr, 1) != pdPASS) {
    invalidateThermal("task_unavailable");
  }
#endif
}

static esp_err_t thermalHandler(httpd_req_t *req) {
  // Send the small cached JSON response promptly, as the video socket already
  // does. This is local to this connection and never waits on sensor reads.
  const int noDelay = 1;
  setsockopt(httpd_req_to_sockfd(req), IPPROTO_TCP, TCP_NODELAY,
             &noDelay, sizeof(noDelay));
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  // The control server has a single task, so these buffers cannot be reused by
  // concurrent handlers. Keep them off its small stack; never hold a cache lock
  // during network writes or a sensor read.
  static ThermalFrame snapshot;
  static char body[ThermalFrame::jsonCapacity];
  bool copied = false;
  if (thermalMutex && xSemaphoreTake(thermalMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
    snapshot = thermalFrame;
    copied = true;
    xSemaphoreGive(thermalMutex);
  }
  if (!copied || !encodeThermalFrame(snapshot, millis(), body, sizeof(body))) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    return httpd_resp_send(req,
      "{\"sensor\":\"MLX90640\",\"fresh\":false,\"message\":\"No fresh thermal frame. Check /status and sensor setup.\"}",
      HTTPD_RESP_USE_STRLEN);
  }
  return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

// GPIO4 is the on-board visible white flash. SD is deliberately unused because
// the usual four-bit SD wiring also uses GPIO4. This is not an IR illuminator.
static constexpr int flashPin = 4;
static constexpr uint8_t flashDuty = 32; // 12.5% duty; no full-power API.
static constexpr ledc_mode_t flashSpeedMode = LEDC_HIGH_SPEED_MODE;
static constexpr ledc_timer_t flashTimer = LEDC_TIMER_2;
static constexpr ledc_channel_t flashChannel = LEDC_CHANNEL_4;
static bool flashReady = false;
static SemaphoreHandle_t lightMutex = nullptr;
static IlluminationLease illumination;

static bool writeFlash(bool enabled) {
  if (!flashReady) return !enabled;
  return ledc_set_duty(flashSpeedMode, flashChannel, enabled ? flashDuty : 0) == ESP_OK
      && ledc_update_duty(flashSpeedMode, flashChannel) == ESP_OK;
}

static void setupFlash() {
  pinMode(flashPin, OUTPUT);
  digitalWrite(flashPin, LOW);
  lightMutex = xSemaphoreCreateMutex();
  if (!lightMutex) return;
  // Use an explicit different timer/channel from camera XCLK's TIMER_0 /
  // CHANNEL_0. Arduino's automatic PWM timer allocation can miss driver-owned
  // camera timers. These IDF APIs work with Arduino-ESP32 2.x and 3.x.
  ledc_timer_config_t timer = {};
  timer.speed_mode = flashSpeedMode;
  timer.duty_resolution = LEDC_TIMER_8_BIT;
  timer.timer_num = flashTimer;
  timer.freq_hz = 5000;
  timer.clk_cfg = LEDC_AUTO_CLK;
  if (ledc_timer_config(&timer) != ESP_OK) return;
  ledc_channel_config_t channel = {};
  channel.gpio_num = flashPin;
  channel.speed_mode = flashSpeedMode;
  channel.channel = flashChannel;
  channel.intr_type = LEDC_INTR_DISABLE;
  channel.timer_sel = flashTimer;
  channel.duty = 0;
  channel.hpoint = 0;
  flashReady = ledc_channel_config(&channel) == ESP_OK;
}

static void enforceLightLease() {
  if (!lightMutex) return;
  const bool connected = WiFi.status() == WL_CONNECTED;
  xSemaphoreTake(lightMutex, portMAX_DELAY);
  if (illumination.expire(millis(), connected)) writeFlash(false);
  xSemaphoreGive(lightMutex);
}

static esp_err_t sendStatus(httpd_req_t *req) {
  enforceLightLease();
  bool enabled = false;
  if (lightMutex) {
    xSemaphoreTake(lightMutex, portMAX_DELAY);
    enabled = illumination.enabled;
    xSemaphoreGive(lightMutex);
  }
  bool thermalFresh = false;
  uint32_t thermalAge = 0, thermalSequence = 0;
  const char *state = thermalMutex ? "cache_busy" : (BIMBOT_THERMAL_ENABLED ? "task_unavailable" : "disabled");
  if (thermalMutex && xSemaphoreTake(thermalMutex, pdMS_TO_TICKS(20)) == pdTRUE) {
    thermalFresh = thermalFrame.fresh(millis());
    thermalAge = thermalFrame.sequence ? uint32_t(millis() - thermalFrame.capturedAt) : 0;
    thermalSequence = thermalFrame.sequence;
    state = thermalState;
    xSemaphoreGive(thermalMutex);
  }
  char body[512];
  snprintf(body, sizeof(body),
      "{\"firmware\":\"bimbot-nightvision/2\",\"startup_profile\":\"retry/2\",\"camera_ready\":%s,"
      "\"stream_target_fps\":%lu,\"stream_profile\":\"fresh/2\","
      "\"stream_staging_active\":%s,\"capabilities\":[%s%s%s],"
      "\"illumination\":{\"enabled\":%s,\"brightness\":%u,\"lease_ms\":%lu},"
      "\"thermal\":{\"enabled\":%s,\"fresh\":%s,\"state\":\"%s\",\"frame_age_ms\":%lu,\"sequence\":%lu}}",
      cameraReady.load() ? "true" : "false", (unsigned long)streamTargetFPS,
      streamStagingActive.load() ? "true" : "false",
      flashReady ? "\"white_led\"" : "", flashReady && BIMBOT_THERMAL_ENABLED ? "," : "",
      BIMBOT_THERMAL_ENABLED ? "\"mlx90640\"" : "", enabled ? "true" : "false",
      (unsigned)(enabled ? flashDuty : 0), (unsigned long)IlluminationLease::durationMs,
      BIMBOT_THERMAL_ENABLED ? "true" : "false", thermalFresh ? "true" : "false", state,
      (unsigned long)thermalAge, (unsigned long)thermalSequence);
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t statusHandler(httpd_req_t *req) {
  return sendStatus(req);
}

static esp_err_t lightUnavailable(httpd_req_t *req, const char *message) {
  // ESP-IDF's httpd_err_code_t has no 503 member on the installed core.
  httpd_resp_set_status(req, "503 Service Unavailable");
  httpd_resp_set_type(req, "text/plain");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return httpd_resp_send(req, message, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t lightHandler(httpd_req_t *req) {
  const size_t length = httpd_req_get_url_query_len(req);
  char query[16];
  bool requested = false;
  if (req->content_len != 0 || length == 0 || length >= sizeof(query)
      || httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK
      || !parseLightQuery(query, requested)) {
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Use only enabled=0 or enabled=1, without a body.");
  }
  if (!flashReady || !lightMutex) {
    return lightUnavailable(req, "White LED initialization failed.");
  }
  xSemaphoreTake(lightMutex, portMAX_DELAY);
  const bool applied = writeFlash(requested);
  illumination.set(applied && requested, millis());
  if (!applied) writeFlash(false);
  xSemaphoreGive(lightMutex);
  if (!applied)
    return lightUnavailable(req, "White LED command failed.");
  return sendStatus(req);
}

static void startControlServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.ctrl_port = 32768;
  config.max_uri_handlers = 3;
  config.recv_wait_timeout = 2;
  config.send_wait_timeout = 2;
  if (httpd_start(&controlServer, &config) != ESP_OK) return;
  httpd_uri_t status = {};
  status.uri = "/status"; status.method = HTTP_GET; status.handler = statusHandler;
  httpd_uri_t light = {};
  light.uri = "/light"; light.method = HTTP_POST; light.handler = lightHandler;
  httpd_uri_t thermal = {};
  thermal.uri = "/thermal"; thermal.method = HTTP_GET; thermal.handler = thermalHandler;
  if (httpd_register_uri_handler(controlServer, &status) != ESP_OK
      || httpd_register_uri_handler(controlServer, &light) != ESP_OK
      || httpd_register_uri_handler(controlServer, &thermal) != ESP_OK) {
    httpd_stop(controlServer);
    controlServer = nullptr;
  }
}

static void reportWiFiDisconnect(WiFiEvent_t event, WiFiEventInfo_t info) {
  const uint8_t reason = info.wifi_sta_disconnected.reason;
  // ASSOC_LEAVE is this sketch's own disconnect before a retry, not a failure
  // of the attempt that follows it.
  if (reason != WIFI_REASON_ASSOC_LEAVE) wifiRetry.failed();
  Serial.printf("Wi-Fi disconnected. Reason code: %u.\n", reason);
  switch (reason) {
    case WIFI_REASON_NO_AP_FOUND:
      Serial.println("Hotspot not found. Check its exact name, power and distance."); break;
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
      Serial.println("Authentication/handshake failed. Check Wi-Fi password, security and signal."); break;
    case WIFI_REASON_ASSOC_TOOMANY:
      Serial.println("Hotspot reports too many clients. Disconnect unused phones/devices."); break;
    default:
      Serial.println("Keep this reason code for troubleshooting."); break;
  }
}

static void *resizeStreamPacket(void *buffer, size_t size) {
  // Keep Wi-Fi's internal RAM available when this board has PSRAM. On the
  // single-buffer/no-PSRAM fallback, the bounded packet uses regular byte RAM.
  const uint32_t caps = psramFound() ? MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT : MALLOC_CAP_8BIT;
  return heap_caps_realloc(buffer, size, caps);
}

static esp_err_t streamHandler(httpd_req_t *req) {
  const int socket = httpd_req_to_sockfd(req);
  const int noDelay = 1;
  // JPEG tails and multipart headers must not wait for a following frame or a
  // delayed acknowledgement. Failure retains the platform's default transport.
  setsockopt(socket, IPPROTO_TCP, TCP_NODELAY, &noDelay, sizeof(noDelay));
  struct ResetStreamState {
    ~ResetStreamState() { streamStagingActive.store(false); }
  } resetStreamState;
  streamStagingActive.store(false);
  StreamPacket packet(resizeStreamPacket);
  httpd_resp_set_type(req, "multipart/x-mixed-replace; boundary=frame");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  while (WiFi.status() == WL_CONNECTED) {
    const uint32_t startedAt = millis();
    camera_fb_t *frame = esp_camera_fb_get();
    if (!frame) return ESP_FAIL;
    if (frame->format != PIXFORMAT_JPEG) {
      esp_camera_fb_return(frame);
      return ESP_FAIL;
    }
    esp_err_t result;
    const bool staged = packet.stage(frame->buf, frame->len);
    streamStagingActive.store(staged);
    if (staged) {
      // Holding a DMA buffer during a slow send can stop capture with two buffers:
      // one is held here and one is queued. Return it first so GRAB_LATEST keeps
      // replacing the waiting image throughout network backpressure.
      esp_camera_fb_return(frame);
      result = httpd_resp_send_chunk(req, packet.data(), packet.size());
    } else {
      // Preserve video on memory-constrained boards or an unusually large JPEG.
      // This fallback holds the camera buffer only until the direct send ends.
      char header[100];
      const int length = snprintf(header, sizeof(header),
          "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", (unsigned)frame->len);
      result = httpd_resp_send_chunk(req, header, length);
      if (result == ESP_OK) result = httpd_resp_send_chunk(req, (const char *)frame->buf, frame->len);
      esp_camera_fb_return(frame);
      if (result == ESP_OK) result = httpd_resp_send_chunk(req, "\r\n", 2);
    }
    if (result != ESP_OK) return result;
    // Include capture/send time in pacing; do not add 100ms to every frame.
    delay(frameDelayMs(startedAt, millis()));
  }
  return ESP_FAIL;
}

static bool initializeCamera() {
  // Power-cycle only the camera sensor before a fresh probe. This does not
  // reset the ESP32 or interrupt its Wi-Fi retry owner.
  pinMode(32, OUTPUT);
  digitalWrite(32, HIGH);
  delay(20);
  digitalWrite(32, LOW);
  delay(100);
  camera_config_t c = {};
  c.pin_pwdn = 32; c.pin_reset = -1; c.pin_xclk = 0;
  c.pin_sccb_sda = 26; c.pin_sccb_scl = 27;
  c.pin_d0 = 5; c.pin_d1 = 18; c.pin_d2 = 19; c.pin_d3 = 21;
  c.pin_d4 = 36; c.pin_d5 = 39; c.pin_d6 = 34; c.pin_d7 = 35;
  c.pin_vsync = 25; c.pin_href = 23; c.pin_pclk = 22;
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.xclk_freq_hz = 20000000; c.pixel_format = PIXFORMAT_JPEG;
  const bool hasPSRAM = psramFound();
  c.frame_size = FRAMESIZE_QVGA; c.jpeg_quality = 12;
  c.fb_count = hasPSRAM ? 2 : 1;
  c.fb_location = hasPSRAM ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  c.grab_mode = hasPSRAM ? CAMERA_GRAB_LATEST : CAMERA_GRAB_WHEN_EMPTY;
  esp_err_t result = esp_camera_init(&c);
  if (result != ESP_OK) {
    Serial.printf("Camera initialization failed: 0x%x. Retrying automatically in 3 seconds.\n", result);
    // The camera driver releases a failed probe/configuration itself. Do not
    // deinitialize a second time or touch a camera used by a stream handler.
    return false;
  }
  Serial.println("Camera initialized. Automatic startup ready.");
  return true;
}

void setup() {
  Serial.begin(115200);
  Serial.printf("Boot reason: %d. Starting automatically.\n", (int)esp_reset_reason());
  setupFlash(); // Always starts OFF; only a leased light command can enable it.
  // Publish a stable mutex before any HTTP task can read it. The optional
  // acquisition task starts only after camera allocation, and never deletes it.
  prepareThermal();
  cameraStartup.begin(millis());
  WiFi.setHostname("bimbot-nightvision");
  WiFi.mode(WIFI_STA);
  // One retry owner (WifiRetry); never interrupt an attempt still in progress.
  WiFi.setAutoReconnect(false);
  WiFi.onEvent(reportWiFiDisconnect, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  wifiRetry.attempted(millis());
  WiFi.begin(ROBOT_WIFI_SSID, ROBOT_WIFI_PASSWORD);
  WiFi.setSleep(false); // Prefer prompt streaming; verify the actual power budget.
  Serial.println("Joining robot hotspot. Password is not printed.");
}

void loop() {
  enforceLightLease(); // Also turns OFF on Wi-Fi loss, independent of streaming.
  if (cameraStartup.due(millis())) {
    const bool ready = initializeCamera();
    cameraStartup.complete(millis(), ready);
    cameraReady.store(ready);
    // Allocate optional sensor resources once, after camera DMA/frame buffers.
    if (ready) startThermal();
  }
  static unsigned long lastWiFiStatusAt = 0;
  static bool announced = false;
  if (WiFi.status() != WL_CONNECTED) {
    announced = false;
    if (millis() - lastWiFiStatusAt >= 5000) {
      lastWiFiStatusAt = millis();
      Serial.printf("Waiting for robot hotspot... Wi-Fi status: %d\n", (int)WiFi.status());
    }
    if (wifiRetry.due(millis())) {
      Serial.println("Retrying the robot hotspot.");
      WiFi.disconnect(false, false);
      delay(100);
      wifiRetry.attempted(millis());
      WiFi.begin(ROBOT_WIFI_SSID, ROBOT_WIFI_PASSWORD);
    }
    delay(50); return;
  }
  // A separate HTTP server/task keeps light commands responsive while the
  // stream handler owns its continuous MJPEG response on port 81.
  if (!controlServer) startControlServer();
  if (cameraReady.load() && !streamServer) {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 81;
    config.ctrl_port = 32769;
    config.max_uri_handlers = 1;
    // Ride out a few seconds of hotspot congestion on the same connection
    // instead of dropping the stream and forcing a full dashboard reconnect.
    config.send_wait_timeout = 5;
    if (httpd_start(&streamServer, &config) == ESP_OK) {
      httpd_uri_t uri = {};
      uri.uri = "/stream"; uri.method = HTTP_GET; uri.handler = streamHandler;
      if (httpd_register_uri_handler(streamServer, &uri) != ESP_OK) {
        httpd_stop(streamServer); streamServer = nullptr;
      }
    }
  }
  if (streamServer && controlServer && !announced) {
    Serial.print("Night stream: http://"); Serial.print(WiFi.localIP()); Serial.println(":81/stream");
    Serial.print("White-light status: http://"); Serial.print(WiFi.localIP()); Serial.println("/status");
    Serial.print("Thermal data: http://"); Serial.print(WiFi.localIP()); Serial.println("/thermal");
    Serial.println("White LED starts OFF. The app renews its 15-second lease while this view is active.");
    announced = true;
  }
  delay(50);
}

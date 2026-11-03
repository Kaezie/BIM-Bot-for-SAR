//choose AI Thinker ESP-cam on Boards
//browser, type 192.168.4.1 on your phone or pc
#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiAP.h>
// NEW: added DHT
#include "DHT.h"
// NEW: added http server
#include "esp_http_server.h"


//
// WARNING!!! Make sure that you have either selected ESP32 Wrover Module,
//            or another board which has PSRAM enabled
//

// Select camera model
//#define CAMERA_MODEL_WROVER_KIT
//#define CAMERA_MODEL_ESP_EYE
//#define CAMERA_MODEL_M5STACK_PSRAM
//#define CAMERA_MODEL_M5STACK_WIDE
#define CAMERA_MODEL_AI_THINKER

#include "camera_pins.h"

// ===================
// WIFI SETTINGS
// ===================
#include "wifi_secrets.h"
WiFiServer server(80);
// NEW: Removed as it is not called



// FIX: removed the unused station static IP (192.168.0.101). This board is the
// robot hotspot at 192.168.4.1; WiFi.config() also switched on an idle
// station interface next to the hotspot.

// FIX: hotspot transmit power. Full power (19.5 dBm) draws the largest current
// spikes from the robot's 5 V regulator. Raise this only if the laptop needs
// more range.
const wifi_power_t HOTSPOT_TX_POWER = WIFI_POWER_15dBm;

// ===================
// NEW: DHT SETTINGS
// ===================
#define DHTPIN 13
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

void startCameraServer();

// Handles exposed by the camera web server (defined in app_httpd.cpp)
extern httpd_handle_t camera_httpd;   // main HTTP server
extern httpd_handle_t stream_httpd;   // MJPEG stream server (not used here)

// --- DHT read cache to respect timing (~1Hz for DHT11) ---
static unsigned long lastDhtMillis = 0;
static float lastTempC = NAN;
static float lastHum   = NAN;


// /dht endpoint handler: returns JSON with temp/humidity
static esp_err_t dht_handler(httpd_req_t *req) {
  unsigned long now = millis();

  // Read at most once per second (DHT11 limitation)
  if ((now - lastDhtMillis) >= 1000 || isnan(lastTempC) || isnan(lastHum)) {
    float h = dht.readHumidity();
    float t = dht.readTemperature(); // Celsius
    if (isnan(h) || isnan(t)) {
      httpd_resp_set_status(req, "503 Service Unavailable");
      httpd_resp_set_type(req, "application/json");
      httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
      const char* err = "{\"ok\":false,\"error\":\"DHT read failed\"}";
      httpd_resp_send(req, err, strlen(err));
      return ESP_OK;
    }
    lastHum   = h;
    lastTempC = t;
    lastDhtMillis = now;
  }

  // Build JSON response
  char resp[160];
  float tempF = lastTempC * 9.0f / 5.0f + 32.0f;
  snprintf(resp, sizeof(resp),
           "{\"ok\":true,\"temp_c\":%.2f,\"temp_f\":%.2f,\"humidity\":%.2f}",
           lastTempC, tempF, lastHum);

  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_send(req, resp, strlen(resp));
  return ESP_OK;
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();
  Serial.println("Booting ESP32-CAM + DHT11 (Serial-only DHT logging)…");

  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  //init with high specs to pre-allocate larger buffers
  if(psramFound()){
    config.frame_size = FRAMESIZE_UXGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
    // FIX: always hand out the newest picture, not the older of two buffers.
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;
  } else {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  // camera init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  sensor_t * s = esp_camera_sensor_get();
  //initial sensors are flipped vertically and colors are a bit saturated
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);//flip it back
    s->set_brightness(s, 1);//up the blightness just a bit
    s->set_saturation(s, -2);//lower the saturation
  }
  //drop down frame size for higher initial frame rate
  s->set_framesize(s, FRAMESIZE_QVGA);

  // NEW: removed since its not used
  //#if defined(CAMERA_MODEL_M5STACK_WIDE)
  //s->set_vflip(s, 1);
  //s->set_hmirror(s, 1);
  //#endif

  // ===================
  // DHT INIT
  // ===================
  dht.begin();
  Serial.println("✅ DHT11 initialized on GPIO13");
  // Optional: short delay to allow DHT to stabilize
  delay(1500);


  // Connect to Wi-Fi network with SSID and password
  Serial.print("Setting up ");
  Serial.println(ssid);
  //WiFi.begin(ssid, password);
  WiFi.mode(WIFI_AP);  // FIX: hotspot only
  WiFi.softAP(ssid, password);
  if (!WiFi.setTxPower(HOTSPOT_TX_POWER)) {
    Serial.println("Could not lower hotspot transmit power");
  }

  // Start camera HTTP server (from ESP32-CAM)
  startCameraServer();

  // --- Register /dht endpoint on the camera server ---
  if (camera_httpd) {
    httpd_uri_t dht_uri = {
      .uri      = "/dht",
      .method   = HTTP_GET,
      .handler  = dht_handler,
      .user_ctx = NULL
    };
    esp_err_t reg_ok = httpd_register_uri_handler(camera_httpd, &dht_uri);
    if (reg_ok == ESP_OK) {
      Serial.println("✅ /dht endpoint registered");
    } else {
      Serial.printf("❌ Failed to register /dht: 0x%x\n", reg_ok);
    }
  } else {
    Serial.println("❌ camera_httpd handle is NULL; cannot register /dht");
  }

  Serial.print("Camera Ready! Use 'http://");
  Serial.print(WiFi.softAPIP());
  Serial.println("' to connect");
  Serial.println("DHT JSON: http://192.168.4.1/dht");
}

void loop() {
  // put your main code here, to run repeatedly:
  delay(10000);
}

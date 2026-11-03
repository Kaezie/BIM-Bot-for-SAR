# Powering the spare camera from the robot

Latest October28 status: conservative-1 is deployed and software-verified
(257Python checks,8browser suites); live acceptance remains pending. See
[the fixed camera/sensor profile](CONSERVATIVE_PROFILE.md) for exact settings,
source-expiry recovery and unchanged firmware/model boundaries. Current physical
comparison has original on robot battery and isolated spare on USB, all6spare
robot/thermal jumpers detached. Thermal reads are intentionally paused. Master
is ON with wheels raised; robot USB unplugged. Restore/test thermal separately
before accepting the full system. Earlier entries below describe prior stages.

## October 28 separate-supply diagnosis in progress

The current connection failure remains unresolved. Main also fails when Night
and thermal requests are paused, and direct original-camera requests fail while
the dashboard process is stopped. An independent supply comparison is the next
physical isolation; previous unloaded voltage readings are not a present load
acceptance. A multimeter is currently unavailable.

The operator confirms IMG_7574.MOV shows the free-standing large-lens board as
the spare/night camera, while the original remains in its black bracket. They
confirm the USB base/cable are available and ALL SIX spare jumper connections
have been removed with the master OFF and USB unplugged. Original wiring and
the spare's camera ribbon are unchanged. USB-base alignment is pending; do not
assume a power-on comparison has happened.

For this test only, the app has THERMAL_DATA_URL blank at process launch, with
Night enabled and motor command URLs blank. Persistent .env and firmware are
unchanged. Thermal is physically disconnected and intentionally unavailable;
it must not be counted as a sensor failure during this comparison. Metadata
capture is armed for120seconds after the first valid user-started video frame.

Before any power, match actual camera/base 5V/GND labels, all socket positions,
and orientation with power disconnected. Leave all six robot/thermal leads OFF
the spare while it is on the USB base. The robot's single switch also supplies
motors; secure all wheels raised before powering the original/AP. Then use USB
only for the isolated spare. Do not use Arduino Upload, serial tools, IO0/BOOT,
or alter the original firmware for this test.

After sign-in while internet is available, join ESP32_CAM, refresh the normal
dashboard, connect Main then Night, and retain the page/network until the timed
capture finishes. Keep the white camera light off for the initial comparison.
Record Main/Night source availability and DHT separately. Do not infer a fully
repaired supply from one successful run: thermal load is also removed, and this
comparison does not distinguish regulator margin, sensor load or a contact fault.

Before eventual restoration, turn OFF and unplug USB/base first. Reconnection
must use actual labels and the retained mapping: camera-power red to5V, white
to adjacentGND; thermal red to3V3, black to the otherGND, yellowSDA toIO14 and
blueSCL toIO13. These are earlier operator-confirmed assignments, not newly
verified hidden endpoints in IMG_7574. The thermal PS-to-P5GND lead stays separate.
Do not reconnect robot supply to a spare still seated/powered on its USB base.
Verify restored wiring before normal thermal/full-load testing.

Prepared 2026-10-18 using the robot photos `IMG_7399.HEIC` and `IMG_7401.HEIC`,
the saved camera inventory, and Ai-Thinker's original ESP32-CAM reference documents.
Updated 2026-10-21: a Sanwa CD800a is now available. User video shows stable
**4.98 V DC** with operator-confirmed black-on-P5-GND/red-on-P5-VCC placement;
the video labels/contact are obscured. Capacity and thermal/transient margin
remain untested. This supersedes the earlier no-meter/no-reading status.

## Current decision

Subsequent `IMG_7496.MOV` shows positive 4.97–4.98 V DC at the contacted pair
in steady sampled views13.7–24.6s. It follows the P9 second-row check; exact labels
are obscured, so retain that attribution as contextual. This supports a bounded
stationary trial from the measured VCC/GND pair, preserving original power and
removing spare USB/base first. It does not establish permanent combined capacity.

Latest comparison, 2026-10-21: USB-powered spare video now works, with
independent 320x240 JPEG decoding. Robot-powered P5 has produced approximately
3.28 V at spare 3V3, but the operator reports video still fails after another
restart. A changed DHCP address remains possible. The operator identifies P9 as
the original camera power source; this does not establish P9 voltage, a separate
supply or capacity for both cameras. Preserve the original connection; verify
a free VCC/GND pair and its DC voltage/polarity before any alternate-header trial.
No P9 pin assignment or wiring change has been made.

Keep the spare camera on its existing ESP32-CAM-MB USB supply until the robot's
regulated power output and spare load capacity have been verified. A USB power
bank mounted on the chassis can support an untethered mounting test if available;
this is separate from the robot battery supply. Do not assume that a USB socket
on the robot/controller supplies power out to another device.

The older robot photograph clearly shows an LM1085-5.0-marked regulator and
headers labelled VCC/GND. It does not establish which header is connected to
regulated 5 V, what the battery arrangement is, or whether the regulator can
support another camera while motors and the original camera operate. The chip
marking does not prove available current or thermal headroom. No robot-side
header or regulator leg has been assigned for a new wire in this guide.

### Later close-up: candidate header P5

The user's later [Unknown-4.jpeg](/Users/christine/Downloads/Unknown-4.jpeg)
shows **P5 IIC** at the right edge above P6/P7. Its visible labels in the photo's
orientation are **GND**, **VCC**, **SDA**, **SCL**, top to bottom. This identifies
the candidate header and pin positions. The later 4.98 V DC reading is consistent
with nominal 5 V at operator-confirmed P5 VCC, but does not demonstrate spare
current capacity. If that output is verified as
regulated 5 V with sufficient capacity, P5 VCC would feed spare 5V and P5 GND
would feed spare GND; SDA/SCL would remain unconnected. This is conditional
wiring guidance, not approval to connect an unverified VCC pin.

### Checking P5 voltage with a digital multimeter

Use a digital multimeter with **DC voltage (V⎓ / DCV)** measurement and insulated
red/black test leads. UNI-T UT33A+ (automatic range) and UT33D+ (manual range)
are examples, not confirmed equipment owned by the operator. Any suitable meter
can be used according to its own manual. An automatic range model is simpler
for this initial check; no current/clamp measurement is needed.

1. Switch the robot off. Leave the spare camera fully disconnected. Unplug laptop
   USB from the robot for this battery-supply check, raise the wheels, and keep
   motor operation stopped.
2. The photographed Sanwa CD800a has integrated leads; no input sockets need
   changing. For a meter with removable leads, fit black to **COM** and red to **V**,
   usually VΩ or VΩmA. Follow the actual meter's labels. Leave a separate 10A/A
   current input unused.
3. Select **DC volts**, not AC V~, current A, resistance Ω or continuity. For
   automatic ranging, select DC V. On a manual meter, start at a range above the
   possible source voltage; 200 V DC is a conservative initial range here. If
   the reading is below 20 V, power off/disconnect the test points, change to
   20 V DC and repeat for a more precise reading. Do not begin on 200 mV or 2 V
   when expecting 5 V.
4. Identify P5 by its actual silkscreen. In Unknown-4.jpeg's orientation, the top
   pin is GND and the next is VCC. Connect black to GND and red to VCC. Prefer
   separately insulated female jumper extensions and insulated probe/grabber
   connections fitted while power is off. Secure the two leads so their exposed
   metal cannot touch each other or nearby pins. Leave SDA/SCL unconnected.
5. With connections secure and wheels clear, switch on using the robot's usual
   battery supply. Record the exact displayed voltage and its sign. The spare
   remains disconnected. Switch off before removing/changing test connections.

A stable positive reading close to **5.0 V** is consistent with a nominal 5 V
output; it is not a full approval to add the spare. A negative reading indicates
reversed probe polarity or incorrectly identified points: switch off and recheck.
Zero, 3.3 V, battery-level voltage, an overload indication or unstable readings
require investigation before camera connection. Record the reading rather than
assuming the port is 5 V from the VCC label.

This measurement checks voltage and polarity only. A multimeter reading does not
establish maximum available current, regulator thermal margin or fast startup
voltage dips. **Never select current/amps mode and place the probes across VCC
and GND to test capacity**; that shorts the supply. A combined VΩmA input is usable
for voltage only when the dial is in the correct voltage mode.

References: [UNI-T UT33+ specifications](https://meters.uni-trend.com/product/ut33plus-series/),
[Fluke DC voltage measurement guide](https://www.fluke.com/en-us/learn/blog/digital-multimeters/how-to-measure-dc-voltage-with-a-digital-multimeter).
The 2026-10-21 P5 reading is recorded above; no spare-camera load/capacity test
has been completed. Keep the spare on USB until the remaining checks pass.

## Camera pins

For the matching Ai-Thinker front view, with the microSD socket at the top and
ESP32-CAM text at the bottom, the top-left pin is **5V** and the pin immediately
below is **GND**. Check the actual printed labels; the board reverses left/right
when turned over.

| Verified source | Spare camera destination |
| --- | --- |
| Regulated +5 V output | Pin explicitly labelled **5V** |
| That supply's return/ground | Adjacent **GND** pin |
| Arduino data/motor/sensor signal | No connection needed for Wi-Fi video |

The separate camera header marked VCC is selectable between 3.3 V and 5 V in the
manufacturer reference schematic; it is not the connection used here. Leave
3V3, VCC, GPIO0 and serial pins unconnected for this installation. GPIO0 must
not be grounded during normal boot. Keep the original camera's DHT GPIO13,
3V3 and GND connections intact.

## After power verification

1. Have a lab/technician identify and measure the robot output, battery range,
   and polarity, and check spare current capacity and voltage stability under
   load. The proposed design target is regulated 5 V with at least 1 A of supply
   capacity reserved for the spare camera; this is engineering headroom, not
   the measured consumption or a verified property of the installed regulator.
2. If the existing rail lacks margin, use a separate suitably rated 5 V switching
   regulator branch from the switched robot supply. Select buck, boost or
   buck-boost only after establishing the battery voltage range. Do not parallel
   two regulators' positive outputs. A new module's output also needs verification.
3. Turn off the robot and disconnect all supplies before changing wires. Disconnect
   the spare's USB cable and remove its ESP32-CAM-MB base for direct header power.
4. Connect two suitably secured power leads: verified +5 V to spare 5V; the same
   source's ground to spare GND. For a shared rail, use a proper parallel branch
   or power distribution connector; preserve the original camera connections.
   Do not use a motor terminal, raw battery, Arduino GPIO or DHT 3V3 as camera power.
5. Mount the spare beside the original lens using an insulating bracket/standoffs.
   Keep bare pads off the chassis, antenna and sensors unobstructed, and wires
   clear of wheels. Do not pull on the camera ribbon.
6. Raise the wheels and make the first power-on test stationary. Confirm that the
   original hotspot starts, the spare rejoins it, and both feeds remain stable.
   Test motor operation separately after the stationary power check. Resets or
   dropouts can indicate power/noise issues; do not disable brownout protection.

Do not connect robot header power and USB/base power to the spare simultaneously.
No direct soldering to the LM1085's legs is proposed.

## What happens in software

The existing spare firmware remains in flash when USB is unplugged. Once the robot
powers both cameras, the spare can join `ESP32_CAM` automatically. Select Night
vision in the dashboard to open it. The camera stays powered with the robot;
selecting a tab does not physically switch its power. No Arduino video wire or
new motor-controller firmware is needed.

The last reported spare stream is `http://192.168.4.2:81/stream`. It is a DHCP
address and can change after restart. This guide does not establish decoded video,
spare-load capacity, installation success or infrared night vision. The
spare currently has only its white flash LED and no separate IR illuminator.

## Sources

- [Ai-Thinker original V1.6 schematic, preserved by Seeed](https://github.com/SeeedDocument/forum_doc/blob/master/reg/ESP32_CAM_V1.6.pdf)
- [Ai-Thinker original product specification, preserved PDF](https://raw.githubusercontent.com/raphaelbs/esp32-cam-ai-thinker/master/assets/ESP32-CAM_Product_Specification.pdf)
- [TI LM1085 reference datasheet](https://www.ti.com/lit/ds/symlink/lm1085.pdf)
- [Robot camera photograph](/Users/christine/Downloads/IMG_7399.HEIC)
- [Robot shield/regulator photograph](/Users/christine/Downloads/IMG_7401.HEIC)

The reference regulator datasheet explains the power/thermal considerations;
the photographed device is HGSEMI-branded, and its complete board wiring and
installation rating have not been established.

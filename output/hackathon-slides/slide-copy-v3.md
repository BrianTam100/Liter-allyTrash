## 1. Recognize. Sort. Connect.

A mobile trash-sorting rover with local vision and a shared dashboard.

## 2. The software and hardware

Laptop: Flask dashboard and local CLIP inference. Two Raspberry Pis: drive relay, and camera/lid control. Arduino plus CNC shield: four stepper motors and mecanum wheels.

## 3. Local CLIP recognition

CLIP ViT-L/14 compares camera frames with text labels. Bottle and cardboard map to recycling. Paper towel and chip bag map to trash. At least three readings across 0.5 seconds create a stable lock. Other labels return no supported item. Relative scores are not accuracy probabilities.

## 4. A detection opens the matching lid

A locked live item sends a bin command over Wi-Fi UDP to the lid Pi. The Pi uses PCA9685 over I2C to drive calibrated servos. Each bin has its own channel. The lid stays open about five seconds after the last matching reading. Photos do not open lids.

## 5. Website, voice and hand controls

Website buttons and throttle use the rover bridge. Grok voice calls a drive tool for spoken directions. Local MediaPipe hand tracking converts wrist-to-fingertip angle to direction over Bluetooth. One browser controls the rover at a time. Missing heartbeats stop the rover after 1.5 seconds.

## 6. Grok voice control

The laptop microphone streams audio to xAI’s realtime API when enabled. Grok interprets spoken directions and calls drive_rover. The bridge maps the direction to a motion or stop command, relayed through the drive Pi to the Arduino. Voice uses cloud AI while CLIP recognition runs locally.

## 7. Every detection has a record

TigerData PostgreSQL stores shared history that computers and phones access through the dashboard. Locked live detections and photo analyses record the item, bin, match, source and time. A unique scan ID prevents duplicate rows. The ledger stores metadata, not camera images. Opening a lid records a collection event but does not sensor-verify a deposit.

## 8. Gemini guidance for unfamiliar items

Submit a photo or describe an item for material guidance, preparation steps and reuse ideas. The cloud guide is separate from the local CLIP scanner. It provides advice without controlling the rover or recording drops. Verify disposal rules locally.

## 9. Photon messaging companion

iMessage, Telegram and dashboard chat share the same companion. It reads the shared Pilot progress and provides sorting advice. A five-minute confirmation code authorizes a proposed collection record. Driving stays with the dashboard controls.

## 10. Recognize. Sort. Connect.

Local vision. Automatic lids. Shared recycling history.

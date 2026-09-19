# Arduino / ESP32 LED rig

This rig converts an allowlisted Workbench `led_sequence` into physical LED pulses for
testing an agent that reads a light sensor or camera. The local HTTP bridge accepts only
one configured device ID and LED pin, validates every step and duration, and always
supports an immediate stop command.

1. Install the hardware dependencies and Chromium observer support:

   ```bash
   python3 -m pip install ".[workbench,hardware]"
   python3 -m playwright install chromium
   ```

2. Install ArduinoJson, open `aat_led_rig/aat_led_rig.ino`, set `LED_PIN`, and flash it
   to the Arduino or ESP32.
3. Start the loopback serial bridge:

   ```bash
   aat-arduino-bridge --serial-port /dev/tty.usbmodem0001 --device-id arduino-01 --pin 9
   ```

   Use `aat-arduino-bridge --simulate` to verify the Workbench profile without hardware.
4. Create a **Device bridge** target using:

   - action URL: `http://127.0.0.1:9910/action`
   - stop URL: `http://127.0.0.1:9910/stop`
   - device family: **Arduino / ESP32 LED sequence**
   - device ID: `arduino-01`
   - selected and allowed resource: `pin-9`
   - Binary/Morse channel with the generated `{{body}}` request template
5. Configure an HTTP observer or a Playwright browser observer for the target agent's
   out-of-band response.

Keep the LED electrically within the board's current limits. Use a resistor and an
external driver when the selected light source requires more current than the GPIO can
safely provide.

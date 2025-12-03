import time
import board
import busio
import displayio
import terminalio
import neopixel
import digitalio
import random
import adafruit_adxl34x
import adafruit_displayio_ssd1306
import i2cdisplaybus
from adafruit_display_text import label
from math import sqrt

# IMPORT THE CUSTOM LIBRARY
from rotary_encoder import RotaryEncoder

# --- HARDWARE SETUP ---

# 1. I2C Setup
i2c = busio.I2C(board.D5, board.D4)

# 2. OLED Display Setup
displayio.release_displays()
display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=128, height=64)

# 3. Accelerometer Setup
accel = adafruit_adxl34x.ADXL345(i2c)

# 4. Rotary Encoder Setup
# Increased debounce_ms to 5 for better stability
encoder = RotaryEncoder(board.D0, board.D1, debounce_ms=5)

# 5. Manual Button Setup
class SimpleButton:
    def __init__(self, pin):
        self.pin = digitalio.DigitalInOut(pin)
        self.pin.direction = digitalio.Direction.INPUT
        self.pin.pull = digitalio.Pull.UP
        self.prev_state = self.pin.value
        self.fell = False 

    def update(self):
        cur_state = self.pin.value
        self.fell = False 
        if cur_state != self.prev_state:
            if not cur_state: # Pressed
                self.fell = True
        self.prev_state = cur_state

button = SimpleButton(board.D2)

# 6. NeoPixel Setup
pixel = neopixel.NeoPixel(board.D3, 1, brightness=0.3)

# --- GLOBAL VARIABLES ---
x_offset, y_offset, z_offset = 0.0, 0.0, 0.0
game_state = "MENU"
score = 0
level = 1
time_limit = 3.0
last_position = 0

# --- HELPER FUNCTIONS ---

def calibrate_accelerometer():
    print("Calibrating...")
    display_text("SYSTEM SETUP", "Calibrating", "Sensors...", "Do not move!")
    x_sum, y_sum, z_sum = 0, 0, 0
    samples = 20
    for _ in range(samples):
        x, y, z = accel.acceleration
        x_sum += x
        y_sum += y
        z_sum += z
        time.sleep(0.05)
    global x_offset, y_offset, z_offset
    x_offset = x_sum / samples
    y_offset = y_sum / samples
    z_offset = (z_sum / samples) - 9.81
    display_text("CALIBRATION", "COMPLETE", "", "Press Button")
    time.sleep(1)

def detect_quake():
    x, y, z = accel.acceleration
    # Apply calibration
    x -= x_offset
    y -= y_offset
    z -= z_offset
    magnitude = sqrt(x*x + y*y + z*z)
    return magnitude > 15.0

def display_text(line1="", line2="", line3="", line4=""):
    main_group = displayio.Group()
    y_positions = [8, 24, 40, 56]
    lines = [line1, line2, line3, line4]
    for i in range(4):
        if lines[i]:
            text_area = label.Label(terminalio.FONT, text=lines[i])
            text_area.x = (128 - text_area.bounding_box[2]) // 2
            text_area.y = y_positions[i]
            main_group.append(text_area)
    display.root_group = main_group

# --- GAME LOGIC ---

def run_menu():
    global game_state, level, time_limit, last_position
    
    pixel.fill((0, 0, 255))
    display_text("REACTOR CORE", "Twist to Select", "Btn to Start", f"Level: {level}")
    
    while True:
        encoder.update()
        button.update()
        
        if button.fell:
            game_state = "PLAY"
            score = 0
            return 

        current_position = encoder.position
        if current_position != last_position:
            if current_position > last_position:
                level = min(10, level + 1)
            else:
                level = max(1, level - 1)
            last_position = current_position
            display_text("REACTOR CORE", "Twist to Select", "Btn to Start", f"Level: {level}")
            time_limit = max(0.8, 3.0 - (level * 0.2))

def run_game():
    global game_state, score, level, time_limit, last_position
    
    # 1. COOLDOWN PHASE (Crucial for fairness)
    display_text("", "GET READY...", "", "")
    pixel.fill((0, 0, 0)) # LED Off
    
    cooldown_start = time.monotonic()
    while (time.monotonic() - cooldown_start) < 0.5:
        # "Flush" the encoder buffer
        encoder.update()
        time.sleep(0.01)

    # 2. SELECT COMMAND
    commands = ["VENT", "QUAKE", "LEFT", "RIGHT"]
    target = random.choice(commands)
    
    pixel.fill((255, 100, 0))
    display_text("WARNING!", "ACTION REQUIRED:", f"> {target} <", f"Time: {time_limit:.1f}s")
    
    start_time = time.monotonic()
    
    # 3. SNAPSHOT ENCODER
    start_enc_pos = encoder.position 
    last_debug_pos = start_enc_pos # Used for printing only when changed
    
    print(f"\n--- NEW ROUND: Target={target} ---") 
    
    while (time.monotonic() - start_time) < time_limit:
        encoder.update()
        button.update()
        
        current_enc_pos = encoder.position
        is_shaking = detect_quake()
        
        input_detected = None
        
        # Calculate Logic
        delta = current_enc_pos - start_enc_pos
        
        # --- DEBUG PRINT ---
        # Only print if the value changed so we don't spam the console
        if current_enc_pos != last_debug_pos:
            print(f"Encoder Moving -> Pos: {current_enc_pos} | Delta: {delta}")
            last_debug_pos = current_enc_pos
        # -------------------
        
        # INPUT DETECTION LOGIC
        if button.fell:
            input_detected = "VENT"
            print("Action Detected: VENT")
        elif is_shaking:
            input_detected = "QUAKE"
            print("Action Detected: QUAKE")
            
        # FORGIVING ROTATION LOGIC (Threshold = 3)
        elif delta >= 3:
            input_detected = "RIGHT"
            print(f"Action Detected: RIGHT (Delta {delta} >= 3)")
        elif delta <= -3:
            input_detected = "LEFT"
            print(f"Action Detected: LEFT (Delta {delta} <= -3)")
            
        if input_detected:
            # Check Result
            if input_detected == target:
                print(">> SUCCESS <<")
                score += 1
                pixel.fill((0, 255, 0))
                display_text("CORE STABLE", "Great Job!", f"Score: {score}", "")
                time.sleep(0.5) 
                if score % 5 == 0:
                    level += 1
                    time_limit = max(0.8, time_limit - 0.2)
                return 
            else:
                # WRONG MOVE
                print(f">> FAIL: Expected {target}, Got {input_detected} <<")
                game_state = "GAMEOVER"
                return
    
    # TIMEOUT
    print(">> FAIL: TIMEOUT <<")
    game_state = "GAMEOVER"

def run_gameover():
    global game_state, score
    pixel.fill((255, 0, 0))
    display_text("MELTDOWN!", "GAME OVER", f"Final Score: {score}", "Btn to Reset")
    
    while True:
        encoder.update()
        button.update()
        if button.fell:
            game_state = "MENU"
            score = 0
            break

# --- MAIN LOOP ---
calibrate_accelerometer()

while True:
    if game_state == "MENU":
        run_menu()
    elif game_state == "PLAY":
        run_game()
    elif game_state == "GAMEOVER":
        run_gameover()
        

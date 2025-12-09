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

# 0. RELEASE RESOURCES FIRST
displayio.release_displays()

# 1. I2C Setup
i2c = busio.I2C(board.D5, board.D4)

# 2. OLED Display Setup
display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=128, height=64)

# 3. Accelerometer Setup
accel = adafruit_adxl34x.ADXL345(i2c)

# 4. Rotary Encoder Setup
encoder = RotaryEncoder(board.D0, board.D1, debounce_ms=5)

# 5. Smart Button Setup
class SmartButton:
    def __init__(self, pin):
        self.pin = digitalio.DigitalInOut(pin)
        self.pin.direction = digitalio.Direction.INPUT
        self.pin.pull = digitalio.Pull.UP
        self.prev_state = self.pin.value
        self.click_count = 0
        self.last_click_time = 0 # Tracks when button was last touched
        self.detected_action = None 

    def update(self):
        self.detected_action = None
        cur_state = self.pin.value
        now = time.monotonic()
        
        # Detect Falling Edge (Press)
        if cur_state != self.prev_state:
            if not cur_state: # Button Down
                if (now - self.last_click_time) < 0.35: 
                    self.click_count += 1
                else:
                    self.click_count = 1 
                self.last_click_time = now # Update the timestamp
        self.prev_state = cur_state
        
        # Resolve Action
        if self.click_count == 1 and (now - self.last_click_time) > 0.35:
            self.detected_action = "SINGLE"
            self.click_count = 0
            
        if self.click_count == 2:
            self.detected_action = "DOUBLE"
            self.click_count = 0

button = SmartButton(board.D2)

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
    x -= x_offset
    y -= y_offset
    z -= z_offset
    magnitude = sqrt(x*x + y*y + z*z)
    
    # Increased Threshold from 15.0 to 20.0
    # This prevents small button vibrations from triggering it
    return magnitude > 20.0

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

def get_difficulty_name(lvl):
    if lvl <= 3: return "EASY"
    if lvl <= 7: return "MEDIUM"
    return "HARD"

# --- GAME LOGIC ---

def run_menu():
    global game_state, level, time_limit, last_position
    
    diff_text = get_difficulty_name(level)
    pixel.fill((0, 0, 255))
    display_text("SELECT LEVEL", f"Level: {level}", f"({diff_text})", "Twist to Change")
    
    while True:
        encoder.update()
        button.update()
        
        if button.detected_action: # Any click starts game
            game_state = "PLAY"
            score = 0
            return 

        current_position = encoder.position
        if current_position != last_position:
            level += 1
            if level > 10: level = 1
            last_position = current_position
            time_limit = max(1.2, 3.0 - (level * 0.18))
            diff_text = get_difficulty_name(level)
            display_text("SELECT LEVEL", f"Level: {level}", f"({diff_text})", "Btn to Start")

def run_game():
    global game_state, score, level, time_limit, last_position
    
    display_text("", "GET READY...", "", "")
    pixel.fill((0, 0, 0)) 
    
    cooldown_start = time.monotonic()
    while (time.monotonic() - cooldown_start) < 0.8:
        encoder.update()
        time.sleep(0.01)

    commands = ["VENT", "PING", "QUAKE", "TWIST"]
    target = random.choice(commands)
    
    pixel.fill((255, 100, 0))
    display_text("WARNING!", "ACTION REQUIRED:", f"> {target} <", f"Time: {time_limit:.1f}s")
    
    start_time = time.monotonic()
    start_enc_pos = encoder.position 
    last_debug_pos = start_enc_pos
    
    print(f"\n--- NEW ROUND: Target={target} ---") 
    
    while (time.monotonic() - start_time) < time_limit:
        encoder.update()
        button.update()
        
        current_enc_pos = encoder.position
        
        # 1. READ RAW SHAKE DATA
        raw_shake = detect_quake()
        
        # 2. APPLY "NOISE FILTER"
        # If the button was pressed recently (within 0.5s), IGNORE shakes.
        # This stops the "button click vibration" from registering as a Quake.
        time_since_click = time.monotonic() - button.last_click_time
        if time_since_click < 0.5:
            is_shaking = False
        else:
            is_shaking = raw_shake # Safe to read sensor
            
        delta = current_enc_pos - start_enc_pos
        input_detected = None
        
        # --- INPUT DETECTION ---
        if button.detected_action == "SINGLE":
            input_detected = "VENT"
            print("Action: VENT (Single Tap)")
        elif button.detected_action == "DOUBLE":
            input_detected = "PING"
            print("Action: PING (Double Tap)")
        elif is_shaking:
            input_detected = "QUAKE"
            print("Action: QUAKE")
        elif abs(delta) >= 1:
            input_detected = "TWIST"
            print("Action: TWIST")
            
        if input_detected:
            if input_detected == target:
                print(">> SUCCESS <<")
                score += 1
                pixel.fill((0, 255, 0))
                display_text("CORE STABLE", "Great Job!", f"Score: {score}", "")
                time.sleep(0.5) 
                
                if score % 5 == 0:
                    level += 1
                    if level > 10: level = 10
                    time_limit = max(1.2, time_limit - 0.18)
                return 
            else:
                print(f">> FAIL: Wanted {target}, Got {input_detected} <<")
                game_state = "GAMEOVER"
                return
    
    print(">> FAIL: TIMEOUT <<")
    game_state = "GAMEOVER"

def run_gameover():
    global game_state, score
    pixel.fill((255, 0, 0))
    display_text("MELTDOWN!", "GAME OVER", f"Final Score: {score}", "Btn to Reset")
    
    while True:
        encoder.update()
        button.update()
        if button.detected_action:
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

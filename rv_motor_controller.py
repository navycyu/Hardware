import tkinter as tk
from tkinter import ttk, messagebox
import struct, threading, time, sys
import serial, serial.tools.list_ports

# python-can
try:
    import can
    from can import Bus
    print("python-can library loaded successfully")
except ImportError:
    print("Error: python-can library not found")
    print("Install with: pip install python-can")
    sys.exit(1)

# -------------------- COM utils --------------------
class COMPortManager:
    @staticmethod
    def get_available_ports():
        ports = serial.tools.list_ports.comports()
        out = []
        for p in ports:
            out.append({
                "device": p.device,
                "description": p.description,
                "hwid": getattr(p, "hwid", "") or "",
                "manufacturer": getattr(p, "manufacturer", "") or "",
                "product": getattr(p, "product", "") or "",
            })
        return out

    @staticmethod
    def find_campro_ports():
        ports = COMPortManager.get_available_ports()
        campro_ports = []
        keywords = ["campro", "realsys", "realsis", "usb", "serial", "ch340", "cp210", "ftdi"]
        for port in ports:
            desc = (port["description"] or "").lower()
            hwid = (port["hwid"] or "").lower()
            mfr  = (port["manufacturer"] or "").lower()
            for kw in keywords:
                if kw in desc or kw in hwid or kw in mfr:
                    campro_ports.append(port); break
        return campro_ports

    @staticmethod
    def test_port_communication(port_name, timeout=2.0):
        try:
            ser = serial.Serial(port_name, 115200, timeout=timeout)
            ser.close()
            return True
        except Exception as e:
            print(f"Port {port_name} test failed: {e}")
            return False

# -------------------- Controller --------------------
class RVMotorController:
    def __init__(self):
        # 먼저 root 생성 (변수/위젯들은 모두 여기에 귀속)
        self.root = tk.Tk()
        self.root.title("RV Motor Controller - CAMPRO CAN")
        self.root.geometry("620x840")
        self.root.minsize(600, 800)
        self.root.resizable(True, True)

        # runtime options (root에 귀속)
        self.id_mode = tk.StringVar(self.root, value="Direct")     # "Direct" or "Base+ID"
        self.tx_profile = tk.StringVar(self.root, value="Legacy")  # "Legacy" or "Standard"

        # states
        self.can_bus = None
        self.motor_id = 1
        self.is_connected = False
        self.selected_port = None

        self.current_speed = 0.0
        self.motor_position = 0.0
        self.motor_temperature = 0

        # presets
        self.STOP_SPEED = 0.0
        self.LOW_SPEED  = 1000.0
        self.MED_SPEED  = 3000.0

        # data monitor variables
        self.tx_data_var = tk.StringVar(self.root, value="--")
        self.rx_data_var = tk.StringVar(self.root, value="--")

        self._build_gui()
        self.auto_detect_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.schedule_status_request()

    # ---------- GUI ----------
    def _build_gui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)
        for c in range(3):
            main.grid_columnconfigure(c, weight=1)

        # Title centered
        ttk.Label(main, text="Motor Speed Control", font=("Arial", 18, "bold"))\
            .grid(row=0, column=0, columnspan=3, pady=(0, 16), sticky="n")

        # COM frame
        port_frame = ttk.LabelFrame(main, text="COM 포트 설정", padding=10)
        port_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        port_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(port_frame, text="포트:").grid(row=0, column=0, sticky="w")
        self.port_combo = ttk.Combobox(port_frame, width=24, state="readonly")
        self.port_combo.grid(row=0, column=1, padx=(6, 6), sticky="ew")
        self.port_combo.bind("<<ComboboxSelected>>", self.on_port_selected)
        ttk.Button(port_frame, text="새로고침", command=self.refresh_ports)\
            .grid(row=0, column=2, padx=(6, 0))

        self.port_info_text = tk.StringVar(self.root, value="포트를 선택해주세요.")
        ttk.Label(port_frame, textvariable=self.port_info_text, foreground="blue")\
            .grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 6))

        ttk.Label(port_frame, text="CAN ID 모드:").grid(row=2, column=0, sticky="w")
        ttk.Combobox(port_frame, state="readonly", width=12,
                     values=["Direct", "Base+ID"], textvariable=self.id_mode)\
            .grid(row=2, column=1, sticky="w")
        ttk.Label(port_frame, text="전송 프로파일:").grid(row=2, column=2, sticky="e", padx=(10,0))
        ttk.Combobox(port_frame, state="readonly", width=12,
                     values=["Legacy", "Standard"], textvariable=self.tx_profile)\
            .grid(row=2, column=2, sticky="w", padx=(90,0))

        self.connect_btn = ttk.Button(port_frame, text="연결", command=self.toggle_connection)
        self.connect_btn.grid(row=3, column=0, columnspan=3, pady=(10, 0))

        # connection status
        connection_frame = ttk.LabelFrame(main, text="연결 상태", padding=10)
        connection_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self.connection_status_text = tk.StringVar(self.root, value="연결 안됨")
        self.connection_status_label = ttk.Label(connection_frame, textvariable=self.connection_status_text, foreground="red")
        self.connection_status_label.grid(row=0, column=0, sticky="w")
        ttk.Label(connection_frame, text=f"Motor ID: {self.motor_id}").grid(row=0, column=1, padx=(20, 0), sticky="w")

        # speed control
        control_frame = ttk.LabelFrame(main, text="속도 제어", padding=12)
        control_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 16))
        self.stop_button = tk.Button(control_frame, text="정지", command=self.stop_motor,
                                     bg="#FF4444", fg="white", font=("Arial", 14, "bold"),
                                     width=12, height=2, state="disabled")
        self.stop_button.grid(row=0, column=0, padx=5, pady=5)
        self.low_button = tk.Button(control_frame, text="저속", command=self.low_speed,
                                    bg="#FFAA00", fg="white", font=("Arial", 14, "bold"),
                                    width=12, height=2, state="disabled")
        self.low_button.grid(row=0, column=1, padx=5, pady=5)
        self.med_button = tk.Button(control_frame, text="중속", command=self.medium_speed,
                                    bg="#0088FF", fg="white", font=("Arial", 14, "bold"),
                                    width=12, height=2, state="disabled")
        self.med_button.grid(row=0, column=2, padx=5, pady=5)

        # motor state
        status_frame = ttk.LabelFrame(main, text="모터 상태", padding=10)
        status_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self.current_status = ttk.Label(status_frame, text="정지", font=("Arial", 12, "bold"))
        self.current_status.grid(row=0, column=0, columnspan=2, pady=(0, 10), sticky="w")

        # motor info (bigger section title)
        info_frame = ttk.LabelFrame(main, padding=10)
        info_frame.configure(labelwidget=ttk.Label(info_frame, text="모터 정보", font=("Arial", 13, "bold")))
        info_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        ttk.Label(info_frame, text="설정 속도:").grid(row=0, column=0, sticky="w")
        self.speed_value = ttk.Label(info_frame, text="0.0 RPM")
        self.speed_value.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(info_frame, text="위치:").grid(row=1, column=0, sticky="w")
        self.position_value = ttk.Label(info_frame, text="0.0 rad")
        self.position_value.grid(row=1, column=1, sticky="w", padx=(10, 0))
        ttk.Label(info_frame, text="온도:").grid(row=2, column=0, sticky="w")
        self.temp_value = ttk.Label(info_frame, text="-- °C")
        self.temp_value.grid(row=2, column=1, sticky="w", padx=(10, 0))

        # manual speed (bigger section title)
        manual_frame = ttk.LabelFrame(main, padding=10)
        manual_frame.configure(labelwidget=ttk.Label(manual_frame, text="수동 속도 설정", font=("Arial", 13, "bold")))
        manual_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        ttk.Label(manual_frame, text="속도 (장치 단위):").grid(row=0, column=0, sticky="w")
        self.manual_speed_entry = ttk.Entry(manual_frame, width=15)
        self.manual_speed_entry.grid(row=0, column=1, padx=(5, 5))
        self.manual_send_button = ttk.Button(manual_frame, text="전송", command=self.send_manual_speed, state="disabled")
        self.manual_send_button.grid(row=0, column=2)

        # data monitor
        data_frame = ttk.LabelFrame(main, text="데이터 모니터", padding=10)
        data_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        ttk.Label(data_frame, text="송신 데이터:").grid(row=0, column=0, sticky="w")
        ttk.Label(data_frame, textvariable=self.tx_data_var).grid(row=0, column=1, sticky="w")
        ttk.Label(data_frame, text="수신 데이터:").grid(row=1, column=0, sticky="w")
        ttk.Label(data_frame, textvariable=self.rx_data_var).grid(row=1, column=1, sticky="w")

        ttk.Button(main, text="종료", command=self.on_closing)\
            .grid(row=8, column=0, columnspan=3, pady=(20, 0))

    # ---------- Port list ----------
    def auto_detect_ports(self):
        try:
            campro_ports = COMPortManager.find_campro_ports()
            all_ports = COMPortManager.get_available_ports()
            self.port_combo["values"] = [p["device"] for p in all_ports]
            if campro_ports:
                self.selected_port = campro_ports[0]["device"]
                self.port_combo.set(self.selected_port)
                self.port_info_text.set(f"CAMPRO 장치 발견: {campro_ports[0]['description']}({self.selected_port})")
            elif all_ports:
                self.selected_port = all_ports[0]["device"]
                self.port_combo.set(self.selected_port)
                self.port_info_text.set(f"일반 포트 선택: {all_ports[0]['description']}")
            else:
                self.port_info_text.set("사용 가능한 COM 포트가 없습니다.")
        except Exception as e:
            self.port_info_text.set(f"포트 검색 오류: {e}")

    def refresh_ports(self):
        self.auto_detect_ports()
        messagebox.showinfo("새로고침", "포트 목록이 새로고침되었습니다.")

    def on_port_selected(self, _=None):
        self.selected_port = self.port_combo.get()
        for p in COMPortManager.get_available_ports():
            if p["device"] == self.selected_port:
                self.port_info_text.set(f"선택됨: {p['description']}({self.selected_port})")
                break

    # ---------- CAN connect ----------
    def toggle_connection(self):
        if self.is_connected: self.disconnect_from_motor()
        else: self.connect_to_motor()

    def connect_to_motor(self):
        if not self.selected_port:
            messagebox.showerror("포트 선택 오류", "COM 포트를 선택해주세요.")
            return
        self.connect_btn.config(state="disabled", text="연결 중...")
        try:
            if not COMPortManager.test_port_communication(self.selected_port):
                raise Exception(f"포트 {self.selected_port} 통신 테스트 실패")

            # try SLCAN, fallback to serial
            try:
                self.can_bus = can.Bus(interface="slcan", channel=self.selected_port,
                                       bitrate=1000000, timeout=0.1)
                print("Connected via SLCAN")
            except Exception as e:
                print(f"SLCAN failed({e}), fallback to 'serial'")
                self.can_bus = can.Bus(interface="serial", channel=self.selected_port,
                                       baudrate=115200, timeout=0.1)

            self.is_connected = True
            self.connection_status_text.set("연결됨")
            self.connection_status_label.config(foreground="green")
            self.stop_button.config(state="normal")
            self.low_button.config(state="normal")
            self.med_button.config(state="normal")
            self.manual_send_button.config(state="normal")
            self.connect_btn.config(state="normal", text="연결 해제")

            self.initialize_motor()
            self.start_can_receiver()
        except Exception as e:
            print(f"CAN connection failed: {e}")
            self.connection_status_text.set("연결 실패")
            self.connection_status_label.config(foreground="red")
            self.connect_btn.config(state="normal", text="연결")
            messagebox.showerror("연결 실패", f"CAN 연결에 실패했습니다:\n{e}")

    def disconnect_from_motor(self):
        if self.is_connected:
            self.stop_motor(); time.sleep(0.05)
            self.is_connected = False
            if self.can_bus:
                self.can_bus.shutdown(); self.can_bus = None
            self.connection_status_text.set("연결 안됨")
            self.connection_status_label.config(foreground="red")
            self.stop_button.config(state="disabled")
            self.low_button.config(state="disabled")
            self.med_button.config(state="disabled")
            self.manual_send_button.config(state="disabled")
            self.connect_btn.config(text="연결", state="normal")
            messagebox.showinfo("연결 해제", "모터 연결이 해제되었습니다.")

    # ---------- Protocol helpers ----------
    def _final_can_id(self):
        base = 0x140 if self.id_mode.get() == "Base+ID" else 0x000
        return (base + self.motor_id) & 0x7FF

    @staticmethod
    def _pack_float_legacy(f32):
        b = struct.pack("<f", float(f32))  # [b0,b1,b2,b3] LE
        d0 = (b[3] >> 3) & 0x1F
        d1 = ((b[3] << 5) & 0xE0) | ((b[2] >> 3) & 0x1F)
        d2 = ((b[2] << 5) & 0xE0) | ((b[1] >> 3) & 0x1F)
        d3 = ((b[1] << 5) & 0xE0) | ((b[0] >> 3) & 0x1F)
        return d0, d1, d2, d3

    def initialize_motor(self):
        """응답모드/원점설정 예시. 장치에 맞게 조정 필요. DLC=8"""
        try:
            for cmd in (0x02, 0x03):
                data = [(self.motor_id >> 8) & 0xFF, self.motor_id & 0xFF, 0x00, cmd, 0,0,0,0]
                msg = can.Message(arbitration_id=0x7FF, data=data, is_extended_id=False)
                self.can_bus.send(msg); time.sleep(0.03)
            print("Motor initialized")
        except Exception as e:
            print(f"Motor initialization failed: {e}")

    # ---------- Commands ----------
    def send_speed_command(self, speed):
        if not self.is_connected:
            messagebox.showerror("연결 오류", "CAN이 연결되지 않았습니다."); return
        try:
            arb = self._final_can_id()
            current_limit = 1500  # mA
            ack = 1

            if self.tx_profile.get() == "Legacy":
                d0, d1, d2, d3 = self._pack_float_legacy(speed)
                data0 = 0x40 | d0              # 속도 명령 + 상위 비트 조각
                data  = [data0, d1, d2, d3,    # 4바이트 패킹
                         (current_limit >> 8) & 0xFF,
                         current_limit & 0xFF,
                         (ack & 0x03),
                         0x00]                  # DLC=8
            else:
                f = struct.pack("<f", float(speed))
                data = [
                    0x40 | (ack & 0x07),
                    f[3], f[2], f[1], f[0],
                    (current_limit >> 8) & 0xFF,
                    current_limit & 0xFF,
                    0x00
                ]

            msg = can.Message(arbitration_id=arb, data=data, is_extended_id=False)
            self.can_bus.send(msg)
            self.current_speed = float(speed)
            hex_str = ' '.join(f'{b:02X}' for b in msg.data)
            self.tx_data_var.set(f"ID:0x{arb:03X} | {hex_str} | 속도:{speed}")
            print(f"TX speed:{speed}  ID:0x{arb:03X}  profile:{self.tx_profile.get()}")

        except Exception as e:
            print(f"Failed to send speed command: {e}")
            messagebox.showerror("명령 전송 오류", f"속도 명령 전송 실패:\n{e}")

    def stop_motor(self):
        self.send_speed_command(self.STOP_SPEED); self.update_status("정지")

    def low_speed(self):
        self.send_speed_command(self.LOW_SPEED); self.update_status("저속 회전 중")

    def medium_speed(self):
        self.send_speed_command(self.MED_SPEED); self.update_status("중속 회전 중")

    def request_motor_status(self):
        if not self.is_connected: return
        try:
            arb = self._final_can_id()
            msg = can.Message(arbitration_id=arb, data=[0xE0,0x02,0,0,0,0,0,0], is_extended_id=False)
            self.can_bus.send(msg)
        except Exception as e:
            print(f"Failed to request motor status: {e}")

    # ---------- RX ----------
    def start_can_receiver(self):
        def loop():
            while self.is_connected:
                try:
                    msg = self.can_bus.recv(timeout=0.1)
                    if msg: self.process_received_message(msg)
                except Exception as e:
                    if self.is_connected: print(f"CAN receive error: {e}"); time.sleep(0.1)
        threading.Thread(target=loop, daemon=True).start()

    def process_received_message(self, msg):
        try:
            if len(msg.data) >= 5:
                ack_status = (msg.data[0] >> 5) & 0x07
                if ack_status == 3:
                    fb = bytes([msg.data[4], msg.data[3], msg.data[2], msg.data[1]])
                    self.motor_position = struct.unpack("<f", fb)[0]
                    hex_str = ' '.join(f'{b:02X}' for b in msg.data)
                    self.root.after(0, self.update_motor_info)
                    self.root.after(0, lambda: self.rx_data_var.set(
                        f"ID:0x{msg.arbitration_id:03X} | {hex_str} | 위치:{self.motor_position:.3f}"
                    ))
        except Exception as e:
            print(f"Message processing error: {e}")

    # ---------- misc ----------
    def send_manual_speed(self):
        try:
            v = float(self.manual_speed_entry.get())
            if -18000 <= v <= 18000:
                self.send_speed_command(v)
                self.update_status(f"수동 속도: {v} RPM")
            else:
                messagebox.showerror("입력 오류", "속도는 -18000 ~ 18000 범위여야 합니다.")
        except ValueError:
            messagebox.showerror("입력 오류", "올바른 숫자를 입력해주세요.")

    def update_status(self, t):
        self.current_status.config(text=t)
        self.speed_value.config(text=f"{self.current_speed:.1f} RPM")

    def update_motor_info(self):
        self.position_value.config(text=f"{self.motor_position:.3f} rad")
        self.temp_value.config(text=f"{self.motor_temperature} °C")

    def schedule_status_request(self):
        if self.is_connected: self.request_motor_status()
        self.root.after(1000, self.schedule_status_request)

    def on_closing(self):
        if self.is_connected: self.disconnect_from_motor()
        self.root.destroy()

# -------------------- main --------------------
def main():
    print("Motor Speed Control GUI - CAMPRO CAN")
    print("CAN: 1Mbps / CAN2.0A, Auto COM detect, SLCAN→serial fallback")
    RVMotorController().root.mainloop()

if __name__ == "__main__":
    main()

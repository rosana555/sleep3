import os
import cv2
import time
import tkinter as tk
from tkinter import ttk
import paho.mqtt.client as mqtt
import numpy as np
import json
from dataclasses import dataclass
from typing import Optional
from PIL import Image, ImageTk

@dataclass
class TrackingStatistics:
    elapsed_seconds: float = 0.0
    total_frames: int = 0
    total_people: int = 0
    total_crossings: int = 0
    total_detections: int = 0
    avg_people_per_sec: float = 0.0
    avg_crossings_per_sec: float = 0.0
    avg_track_duration: float = 0.0
    crossing_prediction_accuracy: float = 0.0
    avg_detection_time: float = 0.0
    avg_tracking_time: float = 0.0
    avg_pose_time: float = 0.0
    avg_intent_time: float = 0.0
    avg_other_time: float = 0.0
    avg_total_time: float = 0.0

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("MQTT Pedestrian Tracker")
        self.root.configure(bg="#121212")
        self.frame_image = None
        self.stats = TrackingStatistics()
        self.predictions = []

        self.broker = "10.241.227.26"
        self.port = 1883
        self.frameChannel = "/output/frames"
        self.predsChannel = "/output/preds"
        self.statsChannel = "/output/stats"

        main_frame = tk.Frame(self.root, bg="#121212")
        main_frame.pack(padx=10, pady=10)

        self.left_panel = tk.Label(main_frame, justify=tk.LEFT, bg="#121212", fg="#FFFFFF", font=("Arial", 12))
        self.left_panel.grid(row=0, column=0, sticky="nw", padx=10)

        self.canvas = tk.Label(main_frame, bg="#1e1e1e")
        self.canvas.grid(row=0, column=1)

        self.right_panel = tk.Label(main_frame, justify=tk.LEFT, bg="#121212", fg="#FFFFFF", font=("Arial", 12))
        self.right_panel.grid(row=0, column=2, sticky="ne", padx=10)

        bottom_frame = tk.Frame(self.root, bg="#121212")
        bottom_frame.pack(pady=(5, 10))

        self.frame_label = tk.Label(bottom_frame, text="Frames: 0", font=("Arial", 12), fg="#00BFFF", bg="#121212")
        self.frame_label.pack(side=tk.LEFT, padx=10)

        self.time_label = tk.Label(bottom_frame, text="Elapsed: 0.00s", font=("Arial", 12), fg="#00BFFF", bg="#121212")
        self.time_label.pack(side=tk.LEFT, padx=10)

        self.pred_label = tk.Label(self.root, text="Predictions: ", font=("Arial", 12), fg="lightblue", bg="#121212")
        self.pred_label.pack(pady=(0, 10))

        control_frame = tk.Frame(self.root, bg="#121212")
        control_frame.pack(pady=(0, 10))

        self.start_button = tk.Button(control_frame, text="Start", font=("Arial", 11),
                                      command=self.start_mqtt, bg="#2E8B57", fg="white", width=10)
        self.start_button.pack(side=tk.LEFT, padx=10)

        self.stop_button = tk.Button(control_frame, text="Stop", font=("Arial", 11),
                                     command=self.stop_mqtt, bg="#B22222", fg="white", width=10)
        self.stop_button.pack(side=tk.LEFT, padx=10)

        self.mqtt_client = mqtt.Client(client_id="output", callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.message_callback_add(self.frameChannel, self.on_message_frame)
        self.mqtt_client.message_callback_add(self.predsChannel, self.on_message_preds)
        self.mqtt_client.message_callback_add(self.statsChannel, self.on_message_stats)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("Connected successfully")
            client.subscribe([(self.frameChannel, 1), (self.predsChannel, 1), (self.statsChannel, 1)])
        else:
            print(f"Connection failed: {rc}")

    def on_message_frame(self, client, userdata, msg):
        img = cv2.imdecode(np.frombuffer(msg.payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            img = cv2.resize(img, (920, 540))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img_pil = Image.fromarray(img)
            img_tk = ImageTk.PhotoImage(image=img_pil)
            self.canvas.configure(image=img_tk)
            self.canvas.image = img_tk

    def on_message_preds(self, client, userdata, msg):
        try:
            preds = json.loads(msg.payload.decode())
            self.predictions = preds
            pred_str = ", ".join(str(p) for p in preds)
            self.pred_label.config(text=f"Crossing Predictions: {pred_str}")
        except Exception as e:
            print(f"Prediction processing error: {e}")

    def on_message_stats(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            self.stats = TrackingStatistics(**data)
            self.update_stats_display()
        except Exception as e:
            print(f"Stats processing error: {e}")

    def update_stats_display(self):
        s = self.stats

        self.frame_label.config(text=f"Frames: {s.total_frames}")
        self.time_label.config(text=f"Elapsed: {s.elapsed_seconds:.2f}s")

        left_text = (
            f"Detection Time: {s.avg_detection_time:.2f} ms\n"
            f"Tracking Time: {s.avg_tracking_time:.2f} ms\n"
            f"Pose Time: {s.avg_pose_time:.2f} ms\n"
            f"Intent Time: {s.avg_intent_time:.2f} ms\n"
            f"Other Time: {s.avg_other_time:.2f} ms\n"
            f"Total Time: {s.avg_total_time:.2f} ms"
        )
        self.left_panel.config(text=left_text)

        # Right-side global stats
        right_text = (
            f"People: {s.total_people}\n"
            f"Crossings: {s.total_crossings}\n"
            f"Detections: {s.total_detections}\n"
            f"People/sec: {s.avg_people_per_sec:.2f}\n"
            f"Crossings/sec: {s.avg_crossings_per_sec:.2f}\n"
            f"Track Duration: {s.avg_track_duration:.2f}s\n"
            #f"Prediction Accuracy: {s.crossing_prediction_accuracy:.2%}"
        )
        self.right_panel.config(text=right_text)

    def start_mqtt(self):
        self.mqtt_client.connect(self.broker, self.port, 32000)
        self.mqtt_client.loop_start()

    def stop_mqtt(self):
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()

if __name__ == '__main__':
    root = tk.Tk()
    app = App(root)
    root.mainloop()

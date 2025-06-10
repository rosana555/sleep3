import os
import cv2
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import paho.mqtt.client as mqtt
import numpy as np
from collections import deque, defaultdict
import queue, threading
import json
from dataclasses import dataclass
from typing import Optional
import matplotlib.pyplot as plt


""" RAZRED ZA NALAGANJE STATISTIKE """
@dataclass
class TrackingStatistics:
    """Container for all tracking statistics with type hints"""
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

def update_stats(data: dict):
    """Update statistics from a dictionary"""
    global stats
    stats = TrackingStatistics(
        elapsed_seconds=data.get('elapsed_seconds', 0.0),
        total_frames=data.get('total_frames', 0),
        total_people=data.get('total_people', 0),
        total_crossings=data.get('total_crossings', 0),
        total_detections=data.get('total_detections', 0),
        avg_people_per_sec=data.get('avg_people_per_sec', 0.0),
        avg_crossings_per_sec=data.get('avg_crossings_per_sec', 0.0),
        avg_track_duration=data.get('avg_track_duration', 0.0),
        crossing_prediction_accuracy=data.get('crossing_prediction_accuracy', 0.0),
        avg_detection_time=data.get('avg_detection_time', 0.0),
        avg_tracking_time=data.get('avg_tracking_time', 0.0),
        avg_pose_time=data.get('avg_pose_time', 0.0),
        avg_intent_time=data.get('avg_intent_time', 0.0),
        avg_other_time=data.get('avg_other_time', 0.0),
        avg_total_time=data.get('avg_total_time', 0.0)
    )

""" POVEZAVA Z MQTT """
broker = "10.241.227.26"
port = 1883
outputChannel = "/output"
frameChannel = f"{outputChannel}/frames"
predsChannel = f"{outputChannel}/preds"
statsChannel = f"{outputChannel}/stats"

curFrames = []  # list of received frame
latest_predictions = []  #trackID, prediction pair for the last received frame (or basically a list of trackIDs which are crossing
stats = TrackingStatistics()

class MQTTProcessor:
    def __init__(self):
        self.consumer = mqtt.Client(client_id="output", callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.consumer.max_inflight_messages_set(10000)

        # Setup callbacks
        self.consumer.on_connect = self.on_connect
        self.consumer.message_callback_add(frameChannel, self.on_message_frame)
        self.consumer.message_callback_add(predsChannel, self.on_message_preds)
        self.consumer.message_callback_add(statsChannel, self.on_message_stats)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("Connected successfully")
            client.subscribe([
                (frameChannel, 1),
                (predsChannel, 1),
                (statsChannel, 1)
            ])
        else:
            print(f"Connection failed with code {rc}")

    def on_message_frame(self, client, userdata, msg):
        global curFrames
        try:
            payload = msg.payload.decode("utf-8")
            if payload.strip() == "-1":  # if server sends this, it means it disconnected
                print("\n===================================== END =====================================\n")
                return
        except Exception as e:
            print(f"Frame processing error: {e}")

        img = cv2.imdecode(
            np.frombuffer(msg.payload, dtype=np.uint8),
            cv2.IMREAD_COLOR
        )
        if img is None or img.size == 0:
            print("Bad frame, skipping")
            return

        curFrames.append(img)

        plt.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        plt.title("Received Frame")
        plt.axis('off')
        #plt.show()

        print("Received frame")

    def on_message_preds(self, client, userdata, msg):
        global latest_predictions
        """
        Handle predictions in format [track_id1, track_id2, ...]
        Example: [55, 56] means track 55 and 56 are crossing
        """
        try:
            preds = json.loads(msg.payload.decode())  # Parse JSON array of ints

            if not isinstance(preds, list):
                raise ValueError("Predictions must be a list of track IDs")

            print(f"Received {len(preds)} crossing predictions:")
            for track_id in preds:
                print(f"PREDICTION! -  Track {track_id}: Crossing")

            latest_predictions = preds

        except Exception as e:
            print(f"Prediction processing error: {e}")
            latest_predictions = []

    def on_message_stats(self, client, userdata, msg):
        global stats
        data = json.loads(msg.payload.decode())
        update_stats(data)
        print(f"\n\nSTATS: {stats}")

    def start(self):
        self.consumer.connect(broker, port, 32000)
        self.consumer.loop_start()

    def stop(self):
        self.consumer.loop_stop()



if __name__ == '__main__':
    print("Starting MQTT processor...")
    processor = MQTTProcessor()
    processor.start()

    # Start worker thread for frame processing
    #worker_thread = threading.Thread(target=worker_loop, daemon=True)
    #worker_thread.start()

    try:
        while True:
            # Main loop - you can access stats anytime via processor.stats_loader
            time.sleep(1)
    except KeyboardInterrupt:
        processor.stop()
        print("Stopped MQTT processor")
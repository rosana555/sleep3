import numpy as np
import cv2
import pytest
import tkinter as tk
import json
import os
from unittest.mock import patch

from server.tempServer.server import processFrames
from input.videoFeed import VideoFeed
from output import App


# -------- Fixtures -------- #

@pytest.fixture
def app_instance():
    root = tk.Tk()
    root.withdraw()  # Hide GUI window during tests
    app = App(root)
    yield app
    root.destroy()  # Clean up properly after test

skip_if_headless = pytest.mark.skipif(
    os.environ.get('DISPLAY', '') == '',
    reason="Headless environment (no DISPLAY)"
)

@skip_if_headless
@pytest.fixture
def video_feed_instance():
    root = tk.Tk()
    root.withdraw()
    app = VideoFeed(root)
    yield app
    root.destroy()


# -------- Tests -------- #

def test_processFrames_runs():
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame_index = 1

    annotated, predictions = processFrames(dummy_frame, frame_index, debug=False)

    assert isinstance(annotated, np.ndarray)
    assert annotated.shape == dummy_frame.shape
    assert isinstance(predictions, dict)


def test_video_feed_gui_elements(video_feed_instance):
    assert hasattr(video_feed_instance, "fps_entry")
    assert hasattr(video_feed_instance, "lbl_path")
    assert callable(video_feed_instance.select_video)
    assert callable(video_feed_instance.use_camera_feed)
    assert callable(video_feed_instance.start_stream)


def test_send_frame_to_server_input(video_feed_instance):
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    try:
        video_feed_instance.send_frame_to_server(1, dummy_frame)
    except Exception as e:
        pytest.fail(f"send_frame_to_server raised an exception: {e}")


def test_output_runs(app_instance):
    dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)
    _, jpeg_bytes = cv2.imencode('.jpg', dummy_img)
    frame_msg = type('Msg', (), {'payload': jpeg_bytes.tobytes()})

    preds_msg = type('Msg', (), {'payload': b'[0, 1, 0, 1]'})

    stats_data = {
        "elapsed_seconds": 1.5,
        "total_frames": 30,
        "total_people": 5,
        "total_crossings": 2,
        "total_detections": 10,
        "avg_people_per_sec": 3.33,
        "avg_crossings_per_sec": 1.11,
        "avg_track_duration": 0.75,
        "crossing_prediction_accuracy": 0.85,
        "unsure_crossing_events": 1,
        "avg_detection_time": 5.1,
        "avg_tracking_time": 4.0,
        "avg_pose_time": 6.2,
        "avg_intent_time": 3.3,
        "avg_other_time": 2.0,
        "avg_total_time": 20.6
    }
    stats_msg = type('Msg', (), {'payload': json.dumps(stats_data).encode('utf-8')})

    app_instance.on_message_frame(None, None, frame_msg)
    app_instance.on_message_preds(None, None, preds_msg)
    app_instance.on_message_stats(None, None, stats_msg)

    assert hasattr(app_instance.canvas, "image")
    assert app_instance.predictions == [0, 1, 0, 1]
    assert app_instance.stats.total_frames == 30
    assert abs(app_instance.stats.avg_total_time - 20.6) < 1e-3


def test_app_gui_elements(app_instance):
    assert hasattr(app_instance, "canvas")
    assert hasattr(app_instance, "predictions")
    assert hasattr(app_instance, "stats")
    assert callable(app_instance.on_message_frame)
    assert callable(app_instance.on_message_preds)
    assert callable(app_instance.on_message_stats)

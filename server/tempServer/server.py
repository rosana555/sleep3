from pathlib import Path
import time
import cv2
import paho.mqtt.client as mqtt
import numpy as np
import tensorflow as tf
import os
import sys
import slidingwindow
from ultralytics import YOLO
from collections import deque, defaultdict
import queue, threading
import csv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         '..',    # up from tempServer
                                         '..',    # up from server
                                         'sleep3-volvo'))

# Prepend it to sys.path so Python can find sortn.py there
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Now this will work
from sortn import *


#TODO: fix the path to slep3volvo
base_path = Path.cwd()
sleep3volvo_path = base_path / 'sleep3-volvo'
print(sleep3volvo_path)

# TODO: add all the flags
#  And add a GPU check (physical_devices) but dunno if here or if in the routine


import sys
print("sys.executable =", sys.executable)
print("sys.path:", "\n  ".join(sys.path))



""" STATISTICS CLASS """

# TODO: popravi total_people (I think it counts trackers rather than unique trackIDs, I think total crossings also might be wrong??
#   avg_crossing_percentage is DEFINITELY wrong, active_tracks is not needed? avg_track_duration is also wrong I think?
class Statistics:
    def __init__(self):
        self.start_time = time.time()
        self.frame_count = 0
        self.total_detections = 0  # Total people detections (bounding boxes)
        self.total_crossing_events = 0  # Total crossing predictions
        self.track_data = defaultdict(lambda: {
            'first_seen': None,
            'last_seen': None,
            'crossing_frames': 0,
            'total_frames': 0
        })
        self.per_frame_stats = []
        self.timing_data = []  # Stores timing metrics per frame

    def update_track(self, track_id, frame_idx, is_crossing):
        track = self.track_data[track_id]
        if track['first_seen'] is None:
            track['first_seen'] = frame_idx
        track['last_seen'] = frame_idx
        track['total_frames'] += 1
        if is_crossing:
            track['crossing_frames'] += 1
            self.total_crossing_events += 1  # Count crossing events

    def update_frame(self, frame_idx, num_people, num_crossing):
        self.frame_count += 1
        self.total_detections += num_people  # Total people detections
        self.per_frame_stats.append({
            'frame_idx': frame_idx,
            'num_people': num_people,
            'num_crossing': num_crossing,
            'timestamp': time.time()
        })

    def update_timing(self, frame_idx, detection, tracking, pose, intent, other, total):
        self.timing_data.append({
            'frame_idx': frame_idx,
            'detection': detection,
            'tracking': tracking,
            'pose': pose,
            'intent': intent,
            'other': other,
            'total': total
        })

    def get_summary(self):
        elapsed = time.time() - self.start_time

        # Unique tracks calculation
        unique_tracks = len(self.track_data)

        # Average people per second
        avg_people_per_sec = self.total_detections / elapsed if elapsed > 0 else 0

        # Average crossings per second
        avg_crossings_per_sec = self.total_crossing_events / elapsed if elapsed > 0 else 0

        # Track durations
        track_durations = [t['total_frames'] for t in self.track_data.values()]
        avg_track_duration = sum(track_durations) / len(track_durations) if track_durations else 0

        # Overall crossing percentage
        if self.total_detections > 0:
            overall_crossing_percentage = (self.total_crossing_events / self.total_detections) * 100
        else:
            overall_crossing_percentage = 0

        # Timing metrics
        n = len(self.timing_data)
        if n > 0:
            avg_detection = sum(t['detection'] for t in self.timing_data) / n
            avg_tracking = sum(t['tracking'] for t in self.timing_data) / n
            avg_pose = sum(t['pose'] for t in self.timing_data) / n
            avg_intent = sum(t['intent'] for t in self.timing_data) / n
            avg_other = sum(t['other'] for t in self.timing_data) / n
            avg_total = sum(t['total'] for t in self.timing_data) / n
        else:
            avg_detection = avg_tracking = avg_pose = avg_intent = avg_other = avg_total = 0.0

        return {
            'elapsed_seconds': round(elapsed, 1),
            'total_frames': self.frame_count,
            'total_people': unique_tracks,  # Unique tracks
            'total_crossings': self.total_crossing_events,  # Total crossing events
            'avg_people_per_sec': round(avg_people_per_sec, 2),
            'avg_crossings_per_sec': round(avg_crossings_per_sec, 2),
            'avg_track_duration': round(avg_track_duration, 1),
            'avg_crossing_percentage': round(overall_crossing_percentage, 1),
            # Timing metrics
            'avg_detection_time': round(avg_detection, 4),
            'avg_tracking_time': round(avg_tracking, 4),
            'avg_pose_time': round(avg_pose, 4),
            'avg_intent_time': round(avg_intent, 4),
            'avg_other_time': round(avg_other, 4),
            'avg_total_time': round(avg_total, 4)
        }

    def save_to_csv(self, filename="statistics.csv"):
        # Save per-frame statistics
        with open(f"per_frame_{filename}", 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['frame_idx', 'num_people', 'num_crossing', 'timestamp'])
            writer.writeheader()
            writer.writerows(self.per_frame_stats)

        # Save track-level statistics
        with open(f"tracks_{filename}", 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'track_id', 'first_seen', 'last_seen',
                'total_frames', 'crossing_frames', 'crossing_percentage'
            ])
            writer.writeheader()
            for track_id, data in self.track_data.items():
                crossing_pct = (data['crossing_frames'] / data['total_frames']) * 100 if data['total_frames'] > 0 else 0
                writer.writerow({
                    'track_id': track_id,
                    'first_seen': data['first_seen'],
                    'last_seen': data['last_seen'],
                    'total_frames': data['total_frames'],
                    'crossing_frames': data['crossing_frames'],
                    'crossing_percentage': round(crossing_pct, 1)
                })




""" YOLO SETUP """

#TODO: add later for gpu
# Load YOLOv8 model and move to CPU
yolo = YOLO('yolov8n.pt')
yolo.to('cpu')
YOLO_CONFIDENCE_THRESHOLD = 0.5

def detect_humans(frame: np.ndarray, conf_thresh=0.5) -> np.ndarray:
    # Convert BGR to RGB and run inference
    results = yolo(frame[..., ::-1])

    # Extract raw detections
    boxes = results[0].boxes
    if boxes is None or boxes.shape[0] == 0:
        return np.zeros((0, 5), dtype=float)

    # Retrieve coordinates, confidence scores, and class IDs
    xyxy = boxes.xyxy.cpu().numpy()       # shape (N,4)
    conf = boxes.conf.cpu().numpy().reshape(-1, 1)  # shape (N,1)
    classes = boxes.cls.cpu().numpy().astype(int)   # shape (N,)

    # COCO class ID for person is 0; keep only human detections
    mask = (classes == 0) & (conf.flatten() >= conf_thresh)
    if not mask.any():
        return np.zeros((0, 5), dtype=float)

    # Stack filtered boxes and confidences
    detections = np.hstack((xyxy[mask], conf[mask]))
    print(f"[YOLO] Filtered {mask.sum()} persons with confidence > {conf_thresh}")
    return detections


""" POSE ESTIMATION SETUP """

# TODO: might have to remove this
os.environ['CUDA_VISIBLE_DEVICES'] = ''    # optional, hides GPUs at OS level

tf_config = tf.compat.v1.ConfigProto(
    allow_soft_placement=True,
    device_count={'GPU': 0},              # <= this kills any GPU device
    gpu_options=tf.compat.v1.GPUOptions(
        allow_growth=True
    )
)

tf_pose_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'sleep3-volvo', 'tf-pose-estimation'))

if tf_pose_path not in sys.path:
    sys.path.insert(0, tf_pose_path)


from tf_pose.estimator import TfPoseEstimator
from tf_pose.networks import get_graph_path

graph_path = get_graph_path('mobilenet_thin', sleep3volvo_path)

pose_model = TfPoseEstimator(
    graph_path,
    target_size=(432,368),
    tf_config=tf_config
)

resize_out_ratio = 4.0 #Adjust based on needs
fps_time = 0
KEYPOINT_CONFIDENCE_THRESHOLD = 0.1


""" SORT SETUP """
mot_tracker = Sort()


""" DENSENET SETUP """
tf.keras.backend.clear_session()
tf.config.run_functions_eagerly(True)

densenet_path = sleep3volvo_path

def load_densenet_model():
    # Try loading with legacy format
    try:
        model = tf.keras.models.load_model(
            f'{sleep3volvo_path}/densenet_2.hdf5',
            compile=False
        )
        model.compile(run_eagerly=True)  # Force eager execution
        return model
    except:
        pass

    # Fallback to JSON loading
    with open(f'{sleep3volvo_path}/densenet_model.json', 'r') as f:
        model = tf.keras.models.model_from_json(
            f.read(),
            custom_objects={'Model': tf.keras.Model}
        )
    model.load_weights('densenet_2.hdf5')
    model.compile(run_eagerly=True)  # Critical for eager execution
    return model

model_j = load_densenet_model()

# 3. SAFE prediction function
def pred_func(X_test):
  predictions = model_j.predict(X_test[0:1], verbose=0)
  Y = np.argmax(predictions[0], axis=0)

  return Y



""" PROCESIRANJE """


def is_blurry(image, threshold=100.0):
    """Check if an image is blurry using the Laplacian variance method."""
    return cv2.Laplacian(image, cv2.CV_64F).var() < threshold

def sharpen_image(image):
    """
    Advanced image sharpening and resolution enhancement:
    1. High-boost filtering (stronger sharpening)
    2. CLAHE for local contrast
    3. Optional upscaling with Lanczos
    4. Post-CLAHE sharpening
    5. Optional edge enhancement
    """
    # Step 1: High-boost filter
    gaussian = cv2.GaussianBlur(image, (0, 0), sigmaX=2)
    high_boost = cv2.addWeighted(image, 1.8, gaussian, -0.8, 0)

    # Step 2: CLAHE
    lab = cv2.cvtColor(high_boost, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    enhanced_lab = cv2.merge((cl, a, b))
    enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    # Step 3: Optional upscaling
    h, w = enhanced.shape[:2]
    if w < 100 or h < 100:
        upscale_factor = 2
        enhanced = cv2.resize(enhanced, (w * upscale_factor, h * upscale_factor), interpolation=cv2.INTER_LANCZOS4)

    # Step 4: Final sharpening
    sharpen_kernel = np.array([[0, -1, 0],
                               [-1, 5.5, -1],
                               [0, -1, 0]])
    sharpened = cv2.filter2D(enhanced, -1, sharpen_kernel)

    # Step 5: Edge enhancement via Laplacian
    laplacian = cv2.Laplacian(sharpened, cv2.CV_64F)
    laplacian = np.clip(laplacian, -15, 15).astype(np.uint8)
    final = cv2.addWeighted(sharpened, 1.0, laplacian, 0.2, 0)

    return final

def resize_with_padding(image, target_size=(432, 368)):
    """Resize image while keeping aspect ratio and padding to fit target size."""
    target_w, target_h = target_size
    h, w = image.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(image, (new_w, new_h))

    top = (target_h - new_h) // 2
    bottom = target_h - new_h - top
    left = (target_w - new_w) // 2
    right = target_w - new_w - left

    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    return padded

def remove_padding(image, original_shape, target_size=(432, 368)):
    target_w, target_h = target_size
    orig_h, orig_w = original_shape

    scale = min(target_w / orig_w, target_h / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)

    top = (target_h - new_h) // 2
    left = (target_w - new_w) // 2

    cropped = image[top:top+new_h, left:left+new_w]
    return cropped


def annotate_frame(frame, trackers, track_intent):
    """Add bounding boxes, track IDs and intent text to frame"""
    for tracker in trackers.astype(int):
        x1, y1, x2, y2, track_id = tracker
        track_id = int(track_id)  # Ensure integer ID

        intent = track_intent.get(track_id, 0)

        color = (0, 0, 255) if intent == 1 else (0, 255, 0)  # Red for crossing, green for not
        label = "CROSSING" if intent == 1 else "NOT CROSSING"

        if x1 >= x2 or y1 >= y2:
            print(f"Invalid coordinates for track {track_id}: ({x1},{y1})-({x2},{y2})")
            continue

        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)

        cv2.putText(frame, f"ID: {track_id}", (int(x1), int(y1) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        cv2.putText(frame, label, (int(x1), int(y1) - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    return frame



rolling_buffer = {}                     # current frames
track_intent  = {}                      # track_id → last predicted intent
stats         = Statistics()            # statistics gathering object
video_writer  = None                    # initialized in worker_thread
debug_path    = "debug_output"          # debug path
output_video_path = "output_video.avi"

def init_video_writer(frame):
    """Initialize video writer with first frame's dimensions"""
    global video_writer
    height, width = frame.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    video_writer = cv2.VideoWriter(output_video_path, fourcc, 30.0, (width, height))


def update_video_writer(frames):
    """Append processed frames to output video"""
    global video_writer
    if not frames:
        return

    if video_writer is None:
        height, width = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        video_writer = cv2.VideoWriter(output_video_path, fourcc, 30.0, (width, height))

    for frame in frames:
        video_writer.write(frame)


def processFrames(frame, frame_ind, debug=False):
    global mot_tracker, rolling_buffer, stats, track_intent, video_writer

    t_start = time.time()
    img_orig = frame.copy()

    # Initialize debug_log if needed
    debug_log = None
    if debug:
        os.makedirs(debug_path, exist_ok=True)
        debug_log = open(f"{debug_path}/frame_{frame_ind:06d}_log.txt", "w")
        print(f"\n=== Frame {frame_ind} ===", file=debug_log)

    # 1) human detection
    t0 = time.time()
    detections = detect_humans(img_orig, YOLO_CONFIDENCE_THRESHOLD)
    t_detection = time.time() - t0

    # 2) update tracker & remember trackers
    t0 = time.time()
    trackers = mot_tracker.update(detections).astype(int)
    last_trackers = trackers.copy()
    t_tracking = time.time() - t0

    # 3) pose estimation for each tracked person
    t0 = time.time()
    for x1, y1, x2, y2, tid in trackers:
        crop = img_orig[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        if is_blurry(crop):
            crop = sharpen_image(crop)

        crop_resized = resize_with_padding(crop, (432, 368))
        poses = pose_model.inference(
            crop_resized, resize_to_default=False, upsample_size=resize_out_ratio
        )

        # Filter low-score keypoints
        for h in poses:
            for k in list(h.body_parts):
                if h.body_parts[k].score < KEYPOINT_CONFIDENCE_THRESHOLD:
                    del h.body_parts[k]
        poses.sort(key=lambda h: h.score, reverse=True)

        # Draw skeleton & overlay
        padded = TfPoseEstimator.draw_humans(crop_resized, poses, imgcopy=True)
        skeleton = remove_padding(padded, crop.shape[:2], (432, 368))

        target_slice = img_orig[y1:y2, x1:x2]
        th, tw = target_slice.shape[:2]
        try:
            skeleton_resized = cv2.resize(skeleton, (tw, th))
            img_orig[y1:y2, x1:x2] = skeleton_resized
        except cv2.error as e:
            print(f"Skipping skeleton paste for track {tid}: {e}")

        # Update rolling buffer
        buf_img = cv2.resize(img_orig[y1:y2, x1:x2], (100, 100))
        rolling_buffer.setdefault(tid, deque(maxlen=16)).append(buf_img)

        # DEBUG: save crops
        if debug:
            cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_crop.jpg", crop)
            cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_skeleton.jpg", skeleton)
    t_pose = time.time() - t0

    # 4) intent prediction
    t0 = time.time()
    predictions = {}
    num_crossing = 0

    # First update all tracks with current intent
    for x1, y1, x2, y2, tid in last_trackers:
        current_intent = track_intent.get(tid, 0)
        is_cross = (current_intent == 1)
        stats.update_track(tid, frame_ind, is_cross)
        if is_cross:
            num_crossing += 1

    # Then process predictions for tracks with full buffer
    for x1, y1, x2, y2, tid in last_trackers:
        seq = list(rolling_buffer.get(tid, []))
        if len(seq) == 16:
            arr = np.stack(seq, axis=2)[None, ...]
            pred = int(pred_func(arr))
            predictions[tid] = pred
            track_intent[tid] = pred
            is_cross = (pred == 1)

            # Update statistics with new intent
            stats.update_track(tid, frame_ind, is_cross)

            # Update crossing count if changed
            if is_cross and not track_intent.get(tid, 0) == 1:
                num_crossing += 1
            elif not is_cross and track_intent.get(tid, 0) == 1:
                num_crossing -= 1

            # DEBUG: save prediction data
            if debug and debug_log:
                np.save(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_input.npy", arr)
                mosaic = np.hstack([cv2.resize(f, (50, 50)) for f in seq])
                cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_sequence.jpg", mosaic)
                print(f"Track {tid}: {'CROSSING' if is_cross else 'NOT CROSSING'}", file=debug_log)
    t_intent = time.time() - t0

    # 5) annotate frame
    annotated = annotate_frame(img_orig.copy(), last_trackers, track_intent)

    # 6) update frame statistics
    stats.update_frame(frame_ind, len(last_trackers), num_crossing)
    if debug:
        cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_annotated.jpg", annotated)
        summary = {
            'frame': frame_ind,
            'num_tracks': int(len(last_trackers)),
            'num_crossing': int(num_crossing),
            'predictions': predictions,
        }
        if debug_log:
            print("Summary:", summary, file=debug_log)
            debug_log.close()

    # 7) cleanup old tracks
    active = {int(t[4]) for t in last_trackers}
    for tid in list(rolling_buffer):
        if tid not in active:
            rolling_buffer.pop(tid, None)
            track_intent.pop(tid, None)
            if debug:
                with open(f"{debug_path}/cleanup.log", "a") as lg:
                    print(f"Cleaned track {tid}", file=lg)

    # 8) write to video
    update_video_writer([annotated])

    # Record timing breakdown
    t_other = time.time() - t_start - (t_detection + t_tracking + t_pose + t_intent)
    stats.update_timing(
        frame_ind,
        t_detection,
        t_tracking,
        t_pose,
        t_intent,
        t_other,
        time.time() - t_start
    )

    return [annotated], predictions

def processFrames_old(frame, frame_ind, debug=False):
    global mot_tracker, rolling_buffer, stats, track_intent, video_writer

    img_orig = frame.copy()


    # 1) human detection
    detections = detect_humans(img_orig, YOLO_CONFIDENCE_THRESHOLD)

    # 2) update tracker & remember trackers for this frame
    trackers = mot_tracker.update(detections).astype(int)
    last_trackers = trackers.copy()

    # 2.1) DEBUG: start/create debug file
    if debug:
        os.makedirs(debug_path, exist_ok=True)
        debug_log = open(f"{debug_path}/frame_{frame_ind:06d}_log.txt", "w")
        print(f"\n=== Frame {frame_ind} ===", file=debug_log)

    # 3) for each tracked person detect pose, create overlay and update rolling_buffer
    for x1,y1,x2,y2,tid in trackers:
        crop = img_orig[y1:y2, x1:x2]  #crop out the tracked person: TODO: danaj
        if crop.size == 0:
            continue

        if is_blurry(crop): #if the image is blurry, sharpen it
            crop = sharpen_image(crop)

        # pad and resize pedestrian crop, so pose estimation estimates better
        crop_resized = resize_with_padding(crop, (432,368))

        # 4) predict pose
        poses = pose_model.inference(
            crop_resized, resize_to_default=False, upsample_size=resize_out_ratio
        )

        # filter low‐score keypoints
        for h in poses:
            for k in list(h.body_parts):
                if h.body_parts[k].score < KEYPOINT_CONFIDENCE_THRESHOLD:
                    del h.body_parts[k]
        poses.sort(key=lambda h: h.score, reverse=True)

        # draw skeleton & overlay
        padded = TfPoseEstimator.draw_humans(crop_resized, poses, imgcopy=True)
        skeleton = remove_padding(padded, crop.shape[:2], (432,368))

        target_slice = img_orig[y1:y2, x1:x2]
        th, tw = target_slice.shape[:2]
        try:
            skeleton_resized = cv2.resize(skeleton, (tw, th))
            img_orig[y1:y2, x1:x2] = skeleton_resized   # draw the detected skeleton onto the original image
        except cv2.error as e:
            print(f"Skipping skeleton paste for track {tid}: {e}")

        # update rolling buffer
        buf_img = cv2.resize(img_orig[y1:y2, x1:x2], (100,100)) # prepare the image for the rolling buffer
        rolling_buffer.setdefault(tid, deque(maxlen=16)).append(buf_img) # add to the rolling buffer (max 16)

        # DEBUG: save crops and estimated pose
        if debug:
            cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_crop.jpg", crop)
            cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_skeleton.jpg", skeleton)

    # 5) intent prediction for any trackID with a full buffer
    predictions = {} # prediction for each ID
    num_crossing = 0 # number of people who are crossing -> for statistics TODO: change
    for x1,y1,x2,y2,tid in last_trackers:
        seq = list(rolling_buffer.get(tid, []))
        if len(seq) == 16:
            arr = np.stack(seq, axis=2)[None,...]
            pred = int(pred_func(arr))
            predictions[tid] = pred
            track_intent[tid] = pred
            is_cross = (pred == 1)
            stats.update_track(tid, frame_ind, is_cross)
            if is_cross:
                num_crossing += 1

            # debug: save input & mosaic
            if debug:
                np.save(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_input.npy", arr)
                mosaic = np.hstack([cv2.resize(f, (50,50)) for f in seq])
                cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_sequence.jpg", mosaic)
                print(f"Track {tid}: {'CROSSING' if is_cross else 'NOT CROSSING'}", file=debug_log)
        else:
            print(f"WARNING: not enough frames in rolling buffer for track {tid}")
            #TODO: add frame duplication

    # 4) annotate frame
    annotated = annotate_frame(img_orig.copy(), last_trackers, track_intent)

    # 5) stats & debug
    stats.update_frame(frame_ind, len(last_trackers), num_crossing)
    if debug:
        cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_annotated.jpg", annotated)
        summary = {
            'frame': frame_ind,
            'num_tracks': int(len(last_trackers)),
            'num_crossing': int(num_crossing),
            'predictions': predictions,
        }
        print("Summary:", summary, file=debug_log)
        debug_log.close()

    # 6) cleanup old tracks
    active = { int(t[4]) for t in last_trackers }
    for tid in list(rolling_buffer):
        if tid not in active:
            rolling_buffer.pop(tid, None)
            track_intent.pop(tid, None)
            if debug:
                # reopen log so file handle still valid
                with open(f"{debug_path}/cleanup.log", "a") as lg:
                    print(f"Cleaned track {tid}", file=lg)

    # 7) write to your shared video_writer
    update_video_writer([annotated])

    return [annotated], predictions


""" INICIALIZACIJA MQTT """

broker = "10.241.227.26" #TODO: spremeni za mqtt broker (prev: 10.241.227.26)
port = 1883
inputChannel = "/input"
outputChannel = "/output"


curFrames = deque(maxlen=16)  # Automatically discards oldest when >16
stats = Statistics()
initialized = False
frame_ind = 0
msg_queue = queue.Queue()
vid_ind = 0



## TEMP FUNCTION, might use:
def publish_frame(client, topic, frame):
    success, buffer = cv2.imencode('.jpg', frame)
    if not success:
        print("Failed to encode frame for publishing")
        return
    payload = buffer.tobytes()
    client.publish(f"{outputChannel}/frames", payload, qos=1)

def publis_predictions(client, topic, predictions):
    pass

def publish_statistic(client, topic, stats):
    pass


def on_message(client, userdata, msg):
    # TODO: 0 -> end of video, -1 -> shutdown
    #  on end of video the buffer should be cleaned?? And the output video?? and the statistics should be renewed??
    global curFrames, stats, initialized, frame_ind, msg_queue, output_video_path, video_writer, vid_ind

    try:
        payload = msg.payload.decode("utf-8")
        if payload.strip() == "-1":
            print("\n===================================== END =====================================\n")
            print(f"{stats.get_summary()}")
            return
        elif payload.strip() == "0":
            print(f"\n############################  DONE RECEIVING VIDEO #{vid_ind}   ##############################\n")
            print(f"{stats.get_summary()}")
            print("##################################################################################")
            vid_ind += 1
            curFrames = deque(maxlen=16)
            stats = Statistics()
            initialized = False
            frame_ind = 0
            msg_queue = queue.Queue()
            video_writer = None
            output_video_path = f"{output_video_path}_{vid_ind}"
    except Exception as e:
        msg_queue.put(msg)
        print("Received frame in on_message!")


def worker_loop():
    global initialized, frame_ind
    while True:
        msg = msg_queue.get()

        try:
            frame_ind += 1
            print(f"Received message {frame_ind}")

            img = cv2.imdecode(
                np.frombuffer(msg.payload, dtype=np.uint8),
                cv2.IMREAD_COLOR
            )
            if img is None or img.size==0:
                print("Bad frame, skipping")
                continue

            #if not initialized:
            #    init_video_writer(img)

            # append to your rolling 16-window
            curFrames.append(img)

            # on first 16 messages you still only need to call processFrames on the *one* new frame
            processed, preds = processFrames(img, frame_ind, debug=True)
            initialized = True

        except Exception as e:
            print("Error in worker_loop:", e)
        finally:
            msg_queue.task_done()

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully")
        client.subscribe(inputChannel, qos=1)
    else:
        print(f"Connection failed with code {rc}")
        # Implement reconnection logic here if needed


server = mqtt.Client(client_id="server", clean_session=True, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

server.connect(broker, port, 180)
server.on_connect = on_connect
server.on_message = on_message
print("Came to here :)")
threading.Thread(target=worker_loop, daemon=True).start()
server.loop_forever()

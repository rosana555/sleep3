from pathlib import Path
import cv2
import paho.mqtt.client as mqtt
import numpy as np
import tensorflow as tf
import os
import slidingwindow


#TODO: fix the path to slep3volvo
base_path = Path.cwd()
sleep3volvo_path = base_path / 'sleep3-volvo'
print(sleep3volvo_path)

# TODO: add all the flags
#  also add the KEYPOINT_CONFIDENCE_THRESHOLD = 0.2
#  And add a GPU check (physical_devices) but dunno if here or if in the routine


import sys
print("sys.executable =", sys.executable)
print("sys.path:", "\n  ".join(sys.path))



""" PROCESSING CLASS """
class Processor:
    def __init__(self):
        st_pescev = 0





""" YOLO SETUP """






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



""" SORT SETUP """


""" DENSENET SETUP """

tf.keras.backend.clear_session()
tf.config.run_functions_eagerly(True)

densenet_path = base_path

def load_densenet_model():
    # Try loading with legacy format
    try:
        model = tf.keras.models.load_model(
            'densenet_2.hdf5',
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


""" INICIALIZACIJA MQTT """

broker = "10.241.227.26" #TODO: spremeni za mqtt broker (prev: 10.241.227.26)
port = 1883
inputChannel = "/input"
outputChannel = "/output"

def on_message(client, userdata, msg):
    processed = msg.payload.decode().upper()
    print("Processed:", processed)
    client.publish(outputChannel, processed)
    #TODO: process messages

def send_frame_to_server(frame_num, frame):
  success, buffer = cv2.imencode('.jpg', frame)
  if not success:
    print("Failed to encode frame", frame_num)
    return

  # Send encoded bytes
  ret = server.publish(f"{outputChannel}/frame", buffer.tobytes(), qos=1, retain=False)
  print(f"Pošiljanje frame {frame_num}: {ret.rc}")

def send_isCrossing_to_server(predict):
  # Send predicton
  ret = server.publish(f"{outputChannel}/crossing", qos=1, retain=False)
  print(f"Pošiljanje  {predict}: {ret.rc}")

server = mqtt.Client("server")
server.connect(broker, port)

#povezava na kanal, kjer bo server pridobival frames
server.subscribe(inputChannel)
server.on_message = on_message
server.loop_forever()





print(f"Running server!!! Base path: {sleep3volvo_path}")
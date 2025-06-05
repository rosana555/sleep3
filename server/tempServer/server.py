# TODO: add all the flags
#  also add the KEYPOINT_CONFIDENCE_THRESHOLD = 0.2
#  And add a GPU check (physical_devices) but dunno if here or if in the routine

"""SKIPPED PART"""
### Pose estimation setup
# os.environ['CUDA_VISIBLE_DEVICES'] = ''  # optional, hides GPUs at OS level
#
# tf_config = tf.compat.v1.ConfigProto(
#     allow_soft_placement=True,
#     device_count={'GPU': 0},  # <= this kills any GPU device
#     gpu_options=tf.compat.v1.GPUOptions(
#         allow_growth=True
#     )
# )
#
# from tf_pose.estimator import TfPoseEstimator
# from tf_pose.networks import get_graph_path
#
# graph_path = get_graph_path('mobilenet_thin')
#
# pose_model = TfPoseEstimator(
#     graph_path,
#     target_size=(432, 368),
#     tf_config=tf_config
# )
#
# resize_out_ratio = 4.0  # Adjust based on needs
# fps_time = 0



print("Running server!!!")
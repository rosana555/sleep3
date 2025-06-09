import subprocess
import os
import sys
import shutil
from pathlib import Path
import stat

def handle_remove_readonly(func, path, exc_info):
    # Clear read-only flag and retry
    os.chmod(path, stat.S_IWRITE)
    func(path)

def run(cmd, cwd=None, shell=False):
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    subprocess.run(cmd, check=True, cwd=cwd, shell=shell)

def main():
    base_path = Path.cwd()
    repo_url = "https://github.com/rosana555/sleep3-volvo"
    repo_name = "sleep3-volvo"
    clone_dir = base_path / repo_name

    # Clone repo
    if clone_dir.exists():
        pass
        #print(f"Removing existing directory {clone_dir}")
        #shutil.rmtree(clone_dir, onerror=handle_remove_readonly)
    else:
        run(["git", "clone", repo_url])
    #run(["git", "clone", repo_url])


    # Install
    tf_pose_path = clone_dir / "tf-pose-estimation"
    run(["pip", "install", "--upgrade", "numpy<2"])
    #run(["pip3", "install", "-r", "requirements.txt"], cwd=tf_pose_path)
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=tf_pose_path)
    run([sys.executable, "-m", "pip", "install", "filterpy"])
    run([sys.executable, "-m", "pip", "install", "tensorflow"])

    # Uninstall old YOLO versions and install new one
    run([sys.executable, "-m", "pip", "uninstall", "-y", "yolov3_tf2", "keras-yolo3"])
    run([sys.executable, "-m", "pip", "install", "ultralytics"])

    """ TF-pose dependencies setup """

    # Build pafprocess and check required files
    paf_path = tf_pose_path / "tf_pose" / "pafprocess"
    required_files = ["pafprocess.i", "pafprocess.cpp", "setup.py"]
    missing = [f for f in required_files if not (paf_path / f).exists()]
    if missing:
        raise FileNotFoundError(f"Missing required files for build: {missing}")
    else:
        print("All necessary build files found.")


    # SWIG installation
    swig_path = clone_dir / "SWIG" / "swigwin-4.3.1" / "swig.exe"

    #swig_path = Path("sleep3-volvo/SWIG/swigwin-4.3.1/swig.exe").resolve()
    if not swig_path.exists():
        raise FileNotFoundError(f"SWIG not found at: {swig_path}")

    # Add SWIG directory to PATH
    swig_dir = swig_path.parent

    print(f"Adding SWIG to PATH: {swig_dir}")
    os.environ["PATH"] = str(swig_dir) + os.pathsep + os.environ["PATH"]

    run([str(swig_path), "-python", "-c++", "pafprocess.i"], cwd=paf_path)
    run(["python", "setup.py", "build_ext", "--inplace"], cwd=paf_path)

    # Check for compiled file
    compiled_files = [
        f for f in os.listdir(paf_path)
        if f.startswith("_pafprocess") and f.endswith(".so")
    ]

    if not compiled_files:
        raise FileNotFoundError("Compiled shared object (_pafprocess*.so) not found.")
    else:
        print(f"Found compiled file: {compiled_files[0]}")

    # Go back to the root of tf-pose-estimation
    project_root = tf_pose_path.resolve()

    # Add to sys.path if not already present
    if str(project_root) not in sys.path:
        print(f"Adding {project_root} to sys.path")
        sys.path.insert(0, str(project_root))

    # Try importing the compiled module
    try:
        from tf_pose.pafprocess import pafprocess
        print("Successfully imported pafprocess.")
    except ImportError as e:
        print("Failed to import pafprocess after build.")
        raise e

    print("DONE")
    server_path = base_path / "server" / "tempServer" / "server.py"
    run([sys.executable, f"{server_path}"])


if __name__ == "__main__":
    main()
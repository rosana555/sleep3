import os
import cv2
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class VideoFeed:
    def __init__(self, master):
        self.master = master
        self.master.title("Live Video Feed Simulator")
        self.master.geometry("500x500")
        self.master.resizable(False, False)

        # Container frame to center content
        container = ttk.Frame(master)
        container.place(relx=0.5, rely=0.5, anchor="center")

        # Grid layout within container
        container.columnconfigure(0, weight=1)

        ttk.Button(container, text="Select Video", command=self.select_video).grid(row=0, column=0, pady=5, sticky="ew")
        ttk.Button(container, text="Use Camera Feed", command=self.use_camera_feed).grid(row=1, column=0, pady=5, sticky="ew")

        self.lbl_path = ttk.Label(container, text="No video selected")
        self.lbl_path.grid(row=2, column=0, sticky="ew")

        ttk.Label(container, text="Frames per second (fps):").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.fps_entry = ttk.Entry(container, justify="center")
        self.fps_entry.insert(0, "1")
        self.fps_entry.grid(row=4, column=0, sticky="ew")

        ttk.Button(container, text="Start Stream", command=self.start_stream).grid(row=5, column=0, pady=10, sticky="ew")

        self.video_path = None
        self.use_camera = False

    def select_video(self):
        path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv")])
        if path:
            self.video_path = path
            self.use_camera = False
            self.lbl_path.config(text=os.path.basename(path))

    def use_camera_feed(self):
        self.video_path = None
        self.use_camera = True
        self.lbl_path.config(text="Using live camera feed")

    def start_stream(self):
        try:
            fps_target = float(self.fps_entry.get())
            if fps_target <= 0:
                raise ValueError("FPS must be positive.")
        except ValueError as e:
            messagebox.showerror("Invalid FPS", str(e))
            return

        delay = 1.0 / fps_target

        if self.use_camera:
            cap = cv2.VideoCapture(0)
        else:
            if not self.video_path:
                messagebox.showerror("Error", "No video or camera selected.")
                return
            cap = cv2.VideoCapture(self.video_path)

        if not cap.isOpened():
            messagebox.showerror("Error", "Failed to open video source.")
            return

        frame_num = 0

        def stream_loop():
            nonlocal frame_num
            ret, frame = cap.read()
            if not ret:
                cap.release()
                messagebox.showinfo("Done", f"Streamed {frame_num} frames.")
                return

            self.send_frame_to_server(frame_num, frame)
            frame_num += 1
            self.master.after(int(delay * 1000), stream_loop)

        self.use_camera = False  # Reset after use
        stream_loop()

    def send_frame_to_server(self, frame_num, frame):
        print(f"Sent frame {frame_num} to server")

if __name__ == '__main__':
    root = tk.Tk()
    app = VideoFeed(root)
    root.mainloop()
    root.destroy()

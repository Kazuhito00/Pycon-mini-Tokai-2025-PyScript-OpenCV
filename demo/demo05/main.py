import js
import io
from js import ImageData, Uint8ClampedArray
import time
import base64
import asyncio
from typing import Tuple, Optional, List, Dict

import cv2
import numpy as np
from pyodide.ffi import create_proxy

from yolov9wholebody25 import (
    preprocess,
    postprocess_nms,
    postprocess_subclass,
    draw_debug,
)

# ビデオとキャンバス要素を取得
video = js.document.querySelector("#myCamera")
canvas = js.document.getElementById("canvas")
context = canvas.getContext("2d")

# YOLOv9準備
net = cv2.dnn.readNet('model/yolov9_n_wholebody25_0100_1x3x192x320.onnx')
model_input_size = (320, 192)

# グローバル変数
camera_stream = None
is_running = True


# カメラストリーム開始用関数
async def start_camera():
    global camera_stream
    media_constraints = js.eval("({video: true, audio: false})")
    camera_stream = await js.navigator.mediaDevices.getUserMedia(media_constraints)
    video.srcObject = camera_stream
    await process_frames()


# カメラストリーム停止用関数
def stop_camera():
    global camera_stream, is_running
    is_running = False

    if camera_stream:
        tracks = camera_stream.getTracks()
        for track in tracks:
            track.stop()

        video.srcObject = None
        camera_stream = None


# フレーム処理用関数
async def process_frames():
    global is_running
    frame_count = 0
    processing_time = 0
    while is_running:
        start_time = time.perf_counter()

        # ビデオフレームをキャンバスに描画
        context.drawImage(video, 0, 0, canvas.width, canvas.height)
        # キャンバスから画像データを取得
        image_data = context.getImageData(0, 0, canvas.width, canvas.height)
        # image_data.data を NumPy 配列に変換（コピー）
        data = np.array(image_data.data.to_py(), dtype=np.uint8)
        image = data.reshape((canvas.height, canvas.width, 4))

        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        image_height, image_width, _ = image.shape

        # 前処理：BGR->RGB、リサイズ、正規化、NCHW
        input_image = preprocess(
            image,
            (model_input_size[0], model_input_size[1]),
        )

        # 推論実施
        net.setInput(input_image, 'images')
        outputs = net.forward('output0')

        # 後処理
        boxes = postprocess_nms(
            outputs,
            (image_width, image_height),
            (model_input_size[0], model_input_size[1]),
            score_th=0.3,
            nms_th=0.3,
        )
        processed_boxes = postprocess_subclass(
            image,
            obj_class_score_th=0.3,
            attr_class_score_th=0.75,
            boxes=boxes,
            disable_generation_identification_mode=False,
            disable_gender_identification_mode=False,
            disable_left_and_right_hand_identification_mode=False,
            disable_headpose_identification_mode=False,
        )

        # 描画
        image: np.ndarray = draw_debug(
            image,
            processed_boxes,
            disable_render_classids=[],
            disable_gender_identification_mode=False,
            disable_left_and_right_hand_identification_mode=False,
            disable_headpose_identification_mode=False,
        )
        cv2.putText(
            image,
            f'{processing_time*1000:.2f} ms',
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            thickness=2,
        )

        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGBA)

        #### ToDo：メモリリーク箇所
        # メモリリークするけど早い処理
        # # NumPy 配列のバッファを使用して Uint8ClampedArray を作成
        # buffer = image.flatten().tobytes()
        # bytes_proxy = create_proxy(buffer)
        # try:
        #     # 新しい ImageData オブジェクトを作成
        #     bytes_buffer = bytes_proxy.getBuffer("u8clamped").data
        #     new_image_data = js.ImageData.new(bytes_buffer, canvas.width,
        #                                       canvas.height)
        #     context.putImageData(new_image_data, 0, 0)
        # finally:
        #     # キャンバスに画像データを描画
        #     bytes_proxy.destroy()
        #     del bytes_proxy, bytes_buffer, new_image_data

        # メモリリークしないけど遅い処理
        height, width, _ = image.shape
        buffer = image.flatten().tobytes()
        js_image = ImageData.new(Uint8ClampedArray.new(buffer), width, height)
        context.putImageData(js_image, 0, 0)
        ####

        end_time = time.perf_counter()
        processing_time = end_time - start_time
        frame_count += 1

        await asyncio.sleep(0)


# async def monitor_memory():
#     while True:
#         if js.performance.memory:
#             memory = js.performance.memory
#             print(
#                 f"Total JS heap size: {memory.totalJSHeapSize / 1024 / 1024:.2f} MB"
#             )
#             print(
#                 f"Used JS heap size: {memory.usedJSHeapSize / 1024 / 1024:.2f} MB"
#             )
#             print(
#                 f"JS heap size limit: {memory.jsHeapSizeLimit / 1024 / 1024:.2f} MB"
#             )
#         else:
#             print("Memory information is not available in this browser.")
#         await asyncio.sleep(5)  # 5秒ごとにメモリ使用量を記録

# stop_camera関数をJavaScriptから呼び出せるようにする
js.window.stopCamera = stop_camera

# スクリプトのロード時にカメラを開始
asyncio.ensure_future(start_camera())
# asyncio.ensure_future(monitor_memory())

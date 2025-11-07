import time
import asyncio

import js
from js import ImageData, Uint8ClampedArray

import cv2
import numpy as np
from pyodide.ffi import create_proxy

from yolox import YOLOX, letterbox, vis

# ビデオとキャンバス要素を取得
video = js.document.querySelector("#myCamera")
canvas = js.document.getElementById("canvas")
context = canvas.getContext("2d")

# YOLOX準備
yolox_input_size = (416, 416)
model = YOLOX(
    modelPath="./model/yolox_nano.onnx",
    input_size=yolox_input_size,
    confThreshold=0.5,
    nmsThreshold=0.5,
    objThreshold=0.5,
    backendId=cv2.dnn.DNN_BACKEND_OPENCV,
    targetId=cv2.dnn.DNN_TARGET_CPU,
)

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

        # 前処理
        input_blob = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        input_blob, letterbox_scale = letterbox(input_blob, yolox_input_size)

        # 推論
        preds = model.infer(input_blob)

        # 描画
        image = vis(preds, image, letterbox_scale)
        cv2.putText(
            image,
            f"{processing_time*1000:.2f} ms",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            thickness=2,
        )
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGBA)

        #### ToDo：メモリリーク箇所
        # # メモリリークするけど早い処理
        # # NumPy 配列のバッファを使用して Uint8ClampedArray を作成
        # buffer = image.flatten().tobytes()
        # bytes_proxy = create_proxy(buffer)
        # try:
        #     # 新しい ImageData オブジェクトを作成
        #     bytes_buffer = bytes_proxy.getBuffer("u8clamped").data
        #     new_image_data = js.ImageData.new(bytes_buffer, canvas.width, canvas.height)
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


# stop_camera関数をJavaScriptから呼び出せるようにする
js.window.stopCamera = stop_camera

# スクリプトのロード時にカメラを開始
asyncio.ensure_future(start_camera())

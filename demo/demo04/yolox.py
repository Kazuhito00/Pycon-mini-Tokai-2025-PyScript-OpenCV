import cv2
import numpy as np

classes = ('person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus',
           'train', 'truck', 'boat', 'traffic light', 'fire hydrant',
           'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog',
           'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe',
           'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
           'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat',
           'baseball glove', 'skateboard', 'surfboard', 'tennis racket',
           'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl',
           'banana', 'apple', 'sandwich', 'orange', 'broccoli', 'carrot',
           'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
           'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop',
           'mouse', 'remote', 'keyboard', 'cell phone', 'microwave', 'oven',
           'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase',
           'scissors', 'teddy bear', 'hair drier', 'toothbrush')


def letterbox(srcimg, target_size=(640, 640)):
    padded_img = np.ones(
        (target_size[0], target_size[1], 3)).astype(np.float32) * 114.0
    ratio = min(target_size[0] / srcimg.shape[0],
                target_size[1] / srcimg.shape[1])
    resized_img = cv2.resize(
        srcimg, (int(srcimg.shape[1] * ratio), int(srcimg.shape[0] * ratio)),
        interpolation=cv2.INTER_LINEAR).astype(np.float32)
    padded_img[:int(srcimg.shape[0] * ratio), :int(srcimg.shape[1] *
                                                   ratio)] = resized_img

    return padded_img, ratio


def unletterbox(bbox, letterbox_scale):
    return bbox / letterbox_scale


def vis(dets, srcimg, letterbox_scale, fps=None):
    res_img = srcimg.copy()

    if fps is not None:
        fps_label = "FPS: %.2f" % fps
        cv2.putText(res_img, fps_label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 1,
                    (0, 0, 255), 2)

    for det in dets:
        box = unletterbox(det[:4], letterbox_scale).astype(np.int32)
        score = det[-2]
        cls_id = int(det[-1])

        x0, y0, x1, y1 = box

        text = '{}:{:.1f}%'.format(classes[cls_id], score * 100)
        font = cv2.FONT_HERSHEY_SIMPLEX
        txt_size = cv2.getTextSize(text, font, 0.4, 1)[0]
        cv2.rectangle(res_img, (x0, y0), (x1, y1), (0, 255, 0), 2)
        cv2.rectangle(res_img, (x0, y0 + 1),
                      (x0 + txt_size[0] + 1, y0 + int(1.5 * txt_size[1])),
                      (255, 255, 255), -1)
        cv2.putText(res_img,
                    text, (x0, y0 + txt_size[1]),
                    font,
                    0.4, (0, 0, 0),
                    thickness=1)

    return res_img


class YOLOX:

    def __init__(self,
                 modelPath,
                 input_size=(640, 640),
                 confThreshold=0.35,
                 nmsThreshold=0.5,
                 objThreshold=0.5,
                 backendId=0,
                 targetId=0):
        self.num_classes = 80
        self.net = cv2.dnn.readNet(modelPath)
        self.input_size = input_size
        self.mean = np.array([0.485, 0.456, 0.406],
                             dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([0.229, 0.224, 0.225],
                            dtype=np.float32).reshape(1, 1, 3)
        self.strides = [8, 16, 32]
        self.confThreshold = confThreshold
        self.nmsThreshold = nmsThreshold
        self.objThreshold = objThreshold
        self.backendId = backendId
        self.targetId = targetId
        self.net.setPreferableBackend(self.backendId)
        self.net.setPreferableTarget(self.targetId)

        self.generateAnchors()

    @property
    def name(self):
        return self.__class__.__name__

    def setBackendAndTarget(self, backendId, targetId):
        self.backendId = backendId
        self.targetId = targetId
        self.net.setPreferableBackend(self.backendId)
        self.net.setPreferableTarget(self.targetId)

    def preprocess(self, img):
        blob = np.transpose(img, (2, 0, 1))
        return blob[np.newaxis, :, :, :]

    def infer(self, srcimg):
        input_blob = self.preprocess(srcimg)

        self.net.setInput(input_blob)
        outs = self.net.forward(self.net.getUnconnectedOutLayersNames())

        predictions = self.postprocess(outs[0])
        return predictions

    def postprocess(self, outputs):
        dets = outputs[0]

        dets[:, :2] = (dets[:, :2] + self.grids) * self.expanded_strides
        dets[:, 2:4] = np.exp(dets[:, 2:4]) * self.expanded_strides

        # get boxes
        boxes = dets[:, :4]
        boxes_xyxy = np.ones_like(boxes)
        boxes_xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.
        boxes_xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.
        boxes_xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.
        boxes_xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.

        # get scores and class indices
        scores = dets[:, 4:5] * dets[:, 5:]
        max_scores = np.amax(scores, axis=1)
        max_scores_idx = np.argmax(scores, axis=1)

        keep = cv2.dnn.NMSBoxesBatched(boxes_xyxy.tolist(),
                                       max_scores.tolist(),
                                       max_scores_idx.tolist(),
                                       self.confThreshold, self.nmsThreshold)

        candidates = np.concatenate(
            [boxes_xyxy, max_scores[:, None], max_scores_idx[:, None]], axis=1)
        if len(keep) == 0:
            return np.array([])
        return candidates[keep]

    def generateAnchors(self):
        self.grids = []
        self.expanded_strides = []
        hsizes = [self.input_size[0] // stride for stride in self.strides]
        wsizes = [self.input_size[1] // stride for stride in self.strides]

        for hsize, wsize, stride in zip(hsizes, wsizes, self.strides):
            xv, yv = np.meshgrid(np.arange(hsize), np.arange(wsize))
            grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
            self.grids.append(grid)
            shape = grid.shape[:2]
            self.expanded_strides.append(np.full((*shape, 1), stride))

        self.grids = np.concatenate(self.grids, 1)
        self.expanded_strides = np.concatenate(self.expanded_strides, 1)

#!/usr/bin/env python3
"""factory.py"""

import os
import sys
import threading
from argparse import ArgumentParser
from queue import Empty, Queue
from time import sleep

import numpy as np
import openvino as ov
import cv2

from iotdemo import ColorDetector, FactoryController, MotionDetector

FORCE_STOP = False


def thread_cam1(q):
    """Function thread_cam1"""
    # MotionDetector
    det = MotionDetector()
    det.load_preset("resources/motion.cfg", "default")

    # Load and initialize OpenVINO
    core = ov.Core()
    model = core.read_model("resources/openvino.xml")

    # Open video clip resources/conveyor.mp4 instead of camera device.
    # pylint: disable=E1101
    cap = cv2.VideoCapture("resources/conveyor.mp4")

    flag = True
    while not FORCE_STOP:
        sleep(0.03)
        _, frame = cap.read()
        if frame is None:
            break

        # Enqueue "VIDEO:Cam1 live", frame info
        q.put(('VIDEO:Cam1 live', frame))

        # Motion detect
        detected = det.detect(frame)
        if detected is None:
            continue

        # Enqueue "VIDEO:Cam1 detected", detected info.
        q.put(('VIDEO:Cam1 detected', detected))

        # abnormal detect
        input_tensor = np.expand_dims(detected, 0)

        if flag is True:
            ppp = ov.preprocess.PrePostProcessor(model)
            ppp.input().tensor() \
                .set_shape(input_tensor.shape) \
                .set_element_type(ov.Type.u8) \
                .set_layout(ov.Layout('NHWC'))  # noqa: ECE001, N400

            ppp.input().preprocess().resize(
                ov.preprocess.ResizeAlgorithm.RESIZE_LINEAR)
            ppp.input().model().set_layout(ov.Layout('NCHW'))
            ppp.output().tensor().set_element_type(ov.Type.f32)

            model = ppp.build()
            compiled_model = core.compile_model(model, "CPU")

            flag = False

        # Inference OpenVINO
        results = compiled_model.infer_new_request({0: input_tensor})
        predictions = next(iter(results.values()))
        probs = predictions.reshape(-1)

        # Calculate ratios
        print(f"{probs}")

        # in queue for moving the actuator 1
        if probs[0] > 0.5:
            print("Bad Items")
            q.put(('PUSH', 1))
        else:
            print("Good Items")

    cap.release()
    q.put(('DONE', None))
    sys.exit(0)


def thread_cam2(q):
    """Function thread_cam2"""
    # MotionDetector
    det = MotionDetector()
    det.load_preset("resources/motion.cfg", "default")

    # ColorDetector
    color = ColorDetector()
    color.load_preset("resources/color.cfg", "default")

    # Open "resources/conveyor.mp4" video clip
    # pylint: disable=E1101
    cap = cv2.VideoCapture("resources/conveyor.mp4")

    while not FORCE_STOP:
        sleep(0.03)
        _, frame = cap.read()
        if frame is None:
            break

        # Enqueue "VIDEO:Cam2 live", frame info
        q.put(('VIDEO:Cam2 live', frame))

        # Detect motion
        detected = det.detect(frame)
        if detected is None:
            continue

        # Enqueue "VIDEO:Cam2 detected", detected info.
        q.put(('VIDEO:Cam2 detected', detected))

        # Detect color
        predict = color.detect(detected)
        if not predict:
            continue

        # Compute ratio
        name, ratio = predict[0]
        ratio = ratio * 100
        print(f"{name}: {ratio:.2f}%")

        # Enqueue to handle actuator 2
        if name == 'blue':
            q.put(('PUSH', 2))

    cap.release()
    q.put(('DONE', None))
    sys.exit(0)


def imshow(title, frame, pos=None):
    """Function imshow"""
    # pylint: disable=E1101
    cv2.namedWindow(title)
    if pos:
        # pylint: disable=E1101
        cv2.moveWindow(title, pos[0], pos[1])
    # pylint: disable=E1101
    cv2.imshow(title, frame)


def main():
    """Function main"""
    global FORCE_STOP

    parser = ArgumentParser(prog='python3 factory.py',
                            description="Factory tool")

    parser.add_argument("-d",
                        "--device",
                        default='/dev/ttyACM0',
                        type=str,
                        help="Arduino port")
    args = parser.parse_args()

    # Create a Queue
    queue = Queue()

    # Create thread_cam1 and thread_cam2 threads and start them.
    thread1 = threading.Thread(target=thread_cam1, args=(queue, ))
    thread2 = threading.Thread(target=thread_cam2, args=(queue, ))

    thread1.start()
    thread2.start()

    with FactoryController(args.device) as ctrl:
        while not FORCE_STOP:
            # pylint: disable=E1101
            if cv2.waitKey(10) & 0xff == ord('q'):
                break

            # get an item from the queue
            # You might need to properly handle exceptions
            # de-queue name and data
            try:
                event = queue.get_nowait()
            except Empty:
                continue

            name, data = event
            # show videos with titles of
            # 'Cam1 live' and 'Cam2 live' respectively.
            if name.startswith('VIDEO:'):
                imshow(name[6:], data)

            # Control actuator, name == 'PUSH'
            elif name == 'PUSH':
                ctrl.push_actuator(data)

            elif name == 'DONE':
                FORCE_STOP = True

            queue.task_done()

    thread1.join()
    thread2.join()

    # pylint: disable=E1101
    cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        os._exit()

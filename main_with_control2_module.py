import sys, time
import argparse

import cv2
import threading
import keyboard
import collections

#from simple_pid import PID
from modules import lidar
from modules import detector_mobilenet as detector
from modules import vision
from modules import control2 as control

parser = argparse.ArgumentParser(description='Drive autonomous')
parser.add_argument('--debug_path', type=str, default="debug/run1", help='debug message name')
args = parser.parse_args()

#config
MAX_FOLLOW_DIST =1.5 #meter
MAX_ALT =  2.5  #m
MAX_SPEED = 3 #m/s
MAX_ROTATION_DEG = 8 #degree

vis = True
movement_x_en = False
movement_yaw_en = True
#end config

MAX_MA_X_LEN = 5
MAX_MA_Z_LEN = 5
MA_X = collections.deque(maxlen=MAX_MA_X_LEN) #Moving Average X
MA_Z = collections.deque(maxlen=MAX_MA_Z_LEN) #Moving Average Z

state = "takeoff" # takeoff land track search
image_width, image_height = detector.get_image_size()
drone_image_center = (image_width / 2, image_height / 2)

debug_image_writer = cv2.VideoWriter(args.debug_path + ".avi",cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'), 25.0,(image_width,image_height))

controlThread = threading.Thread(target=control.main, args=(args.debug_path,))

def setup():
    print("connecting lidar")
    lidar.connect_lidar("/dev/ttyTHS1")

    print("setting up detector")
    detector.initialize_detector()

    print("connecting to drone")
    control.connect_drone('/dev/ttyACM0')
    #drone.connect_drone('127.0.0.1:14551')

def track():
    global state
    print("State = TRACKING")

    while True:

        if keyboard.is_pressed('q'):  # if key 'q' is pressed 
            print("closing because of press Q")
            land()
            break # finishing the loop

        detections, fps, image = detector.get_detections()

        if len(detections) > 0:
            person_to_track = detections[0] # only track 1 person
            
            person_to_track_center = person_to_track.Center # get center of person to track

            x_delta = vision.get_single_axis_delta(drone_image_center[0],person_to_track_center[0]) # get x delta 
            y_delta = vision.get_single_axis_delta(drone_image_center[1],person_to_track_center[1]) # get y delta

            lidar_on_target = vision.point_in_rectangle(drone_image_center,person_to_track.Left, person_to_track.Right, person_to_track.Top, person_to_track.Bottom) #check if lidar is pointed on target

            lidar_distance = lidar.read_lidar_distance()[0] # get lidar distance in meter
            
            MA_Z.append(lidar_distance)
            MA_X.append(x_delta)

            velocity_x_command = 0

            if movement_x_en and lidar_distance > 0 and lidar_on_target and len(MA_Z) > 0: #only if a valid lidar value is given change the forward velocity. Otherwise keep previos velocity (done by arducopter itself)
                
                sum_moving_avg = 0
                for i in range(MAX_MA_Z_LEN):
                    sum_moving_avg += MA_Z[i]

                lider_distance_moving_avg = sum_moving_avg / MAX_MA_Z_LEN
                z_delta = lider_distance_moving_avg - MAX_FOLLOW_DIST

                control.setXdelta(z_delta)

                # debug_writerDepth(z_delta, velocity_x_command)
                # drone.send_movement_command_XYZ(velocity_x_command,0,0)

            #yaw command > PID and moving average
            yaw_command = 0

            if movement_yaw_en and len(MA_X) > 0:
                control.setXdelta(x_delta)
                yaw_command = control.getMovementJawAngle()

            if vis:
                #draw lidar distance
                lidar_vis_x = image_width - 50
                lidar_vis_y = image_height - 50
                lidar_vis_y2 = int(image_height - lidar_distance * 200)
                cv2.line(image, (lidar_vis_x,lidar_vis_y), (lidar_vis_x, lidar_vis_y2), (0, 255, 0), thickness=10, lineType=8, shift=0)
                cv2.putText(image, "distance: " + str(round(lidar_distance,2)), (image_width - 300, 200), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 

                #draw path
                cv2.line(image, (int(drone_image_center[0]), int(drone_image_center[1])), (int(person_to_track_center[0]), int(person_to_track_center[1])), (255, 0, 0), thickness=10, lineType=8, shift=0)

                #draw bbox around target
                cv2.rectangle(image,(int(person_to_track.Left),int(person_to_track.Bottom)), (int(person_to_track.Right),int(person_to_track.Top)), (0,0,255), thickness=10)

	            #show drone center
                cv2.circle(image, (int(drone_image_center[0]), int(drone_image_center[1])), 20, (0, 255, 0), thickness=-1, lineType=8, shift=0)

                #show trackable center
                cv2.circle(image, (int(person_to_track_center[0]), int(person_to_track_center[1])), 20, (0, 0, 255), thickness=-1, lineType=8, shift=0)

                #show stats
                cv2.putText(image, "fps: " + str(round(fps,2)) + " yaw: " + str(round(yaw_command,2)) + " forward: " + str(round(velocity_x_command,2)) , (50, 50), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 
                cv2.putText(image, "lidar_on_target: " + str(lidar_on_target), (50, 100), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 
                cv2.putText(image, "x_delta: " + str(round(x_delta,2)) + " y_delta: " + str(round(y_delta,2)), (50, 150), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 

                visualize(image)

        else:
            return "search"
def search():
    print("State = SEARCH")
    start = time.time()
    
    while time.time() - start < 40:
        detections, fps, image = detector.get_detections()
        
        print("searching: " + str(len(detections)))
        
        if len(detections) > 0:
            return "track"

        if vis:
            cv2.putText(image, "searching target. Time left: " + str(40 - (time.time() - start)), (50, 50), cv2.FONT_HERSHEY_SIMPLEX , 1, (0, 0, 255), 3, cv2.LINE_AA) 
            visualize(image)

    return "land"

def takeoff():
    control.print_drone_report()
    print("State = TAKEOFF")
    control.arm_and_takeoff(MAX_ALT) #start control when drone is ready
    controlThread.start()
    return "search"

def land():
    print("State = LAND")
    control.close_control_loop()
    control.land()
    detector.close_camera()
    #controlThread.join()
    sys.exit(0)

def visualize(img):
   # cv2.imshow("out", img)
    
   # cv2.waitKey(1)
    debug_image_writer.write(img)
    return





setup()

while True:
    # main program loop

    if state == "track":
        control.set_system_state("track")
        state = track()

    elif state == "search":
        control.set_system_state("search")
        state = search()
    
    elif state == "takeoff":
        state = takeoff()

    elif state == "land":
        state = land()
    



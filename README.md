# fomo-face-tracking-with-a-uno-q-and-stepper-motors
This is a project of fomo facetracking with a arduino uno q, 2 stepper motors, and a phone stream to the Uno Q 
To do this project, you will need a couple of  things 
a phone with a hotspot (this code was only used with a iphone im unsure if it works with an Android)
2 a4988 drivers
2 100uf capacitors
a bunch of jumper wires and a breadboard 
a 3d printer or the ability to fabricate a mount for the steppers and phone
An Arduino Uno Q
2 stepper motors

<img width="1472" height="1640" alt="image" src="https://github.com/user-attachments/assets/c657d3f8-92a9-4a90-9b54-cb3ca49cc21f" />

This guide explains how to assemble and troubleshoot a stepper-motor-driven phone tracking system. The first thing you need to do is wire the stepper motors. Make sure the long leg of the capacitor is connected to VMOT, and follow the directions in the picture above. For step mode selection: connect SLEEP/RESET to 3v3; connect MS1, MS2, and MS3 to 3v3 for 1/16th step; for 1/8th step, use GND-3v3-GND; for 1/4th step, use 3v3-GND-GND; and for full step, use GND-GND-GND. Please note that I used a 1/16th step, as the code does not support other modes. For the stepper motor wires, my configuration was b1 black, a1 green, b2 blue, and a2 red, but wire colour assignments can vary between stepper models, so use a multimeter to confirm which wires correspond to which coils. 
The code is designed for the Arduino App Lab, which should be used to enable the face stream. Follow the instructions given in the Python output. Use Safari for all operations. Download the required component to activate camera support.
I have included the file containing my design for the stepper mounts and phone frame. Verify all dimensions carefully before printing. 


The upper stepper motor fails to return the phone to its original position if it lowers too far. This issue is primarily caused by insufficient current being supplied to the stepper due to the driver type used.



Credit to https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet for the face tracking model.

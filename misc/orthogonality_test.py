import numpy as np
from icecream import ic

field_size = 5

print("Test 1: Diagonal Tags")

#instantiate arrays + tags
p1 = [0,2,4,1,1,3] + [0,2,0,0,0,0,0,0]
p2 = [0,1,0,1,0,1] + [1,2,4,1,0,0,0,0]
p3 = [1,2,1,4,3,3] + [0,0,2,3,1,1,0,0]
p4 = [2,2,3,3,4,4] + [0,0,0,0,3,2,2,0]


u1 = np.array(p1)
u2 = np.array(p2)
u3 = np.array(p3)
u4 = np.array(p4)

u = list([u1,u2,u3,u4])

print(u1)

print((u1 @ u1) % field_size)

for packet in u:
    print((packet @ packet) % field_size)



for packet in u:
    ic(packet)
    for e in u:
        ic(e)
        ic("innderproduct equals", ((packet @ e) % field_size))



print("Test 2: Full Tags")

#instantiate arrays + tags
p1 = [0,2,4,1,1,3] + [0,2,0,0,0,0,0,0]
p2 = [0,1,0,1,0,1] + [1,2,4,1,0,0,0,0]
p3 = [1,2,1,4,3,3] + [0,0,2,3,1,1,0,0]
p4 = [2,2,3,3,4,4] + [0,0,0,0,3,2,2,0]


u1 = np.array(p1)
u2 = np.array(p2)
u3 = np.array(p3)
u4 = np.array(p4)

u = list([u1,u2,u3,u4])

print(u1)

print((u1 @ u1) % field_size)

for packet in u:
    print((packet @ packet) % field_size)



for packet in u:
    ic(packet)
    for e in u:
        ic(e)
        ic("innderproduct equals", ((packet @ e) % field_size))


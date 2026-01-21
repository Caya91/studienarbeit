import numpy as np
from icecream import ic

field_size = 5

print("Test 2: Full Tags")

#instantiate arrays + tags
p1 = [0,2,4,1,1,3] + [0,2,0,0,0,0,0,0]
p2 = [0,1,0,1,0,1] + [1,2,4,1,0,0,0,0]
p3 = [1,2,1,4,3,3] + [1,2,1,2,2,1,0,0]
p4 = [2,2,3,3,4,4] + [1,3,3,2,2,2,1,0]


u1 = np.array(p1)
u2 = np.array(p2)
u3 = np.array(p3)
u4 = np.array(p4)

u = list([u1,u2,u3,u4])

print(u1)

print("self inner product should be 0")

for packet in u:
    print((packet @ packet) % field_size)


print("inner product to packet before should be 0")

for i, packet in enumerate(u):
    if i == 0:
        continue
    ic( u[i-1], packet, (packet @ u[i-1]) % field_size)


print("inner product to all packages packet before should be 0")

for packet in u:
    ic(packet)
    for e in u:
        ic(e, packet, ((packet @ e) % field_size))

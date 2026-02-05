import numpy as np


def prf(gen_id, seed):
    if seed == 1:
        return [2,3,1]
    if seed == 2:
        return [1,3,2]


mod = 5

p1 = [1,3,4,2,1,3]
p2 = [4,4,0,1,2,1]
p3 = [0,1,4,0,3,3]

P = np.array([p1,p2,p3])
print(P)

# hier pakte mir Matrix A codieren  mod 5

A= np.array([
    [1,0,3],
    [0,2,4],
    [1,3,0]
    ])

#Resultat sollte sein:

C=np.array(
    [[1,1,1,2,0,2],
    [3,2,1,2,1,4],
    [3,0,4,0,2,1]
])

# Resultat berechnen

C_rech = (A @ P ) % 5

print(C_rech)

# coded paket

A_C = np.concatenate((A,C_rech),axis = 1)

print(A_C)

# generating keys
gen_id = 1
seed = 2


K1 = prf(gen_id, seed=1)
K2 = prf(gen_id, seed=2)

print("K1:", K1)
print("K2:", K2)


#calculating tags
# t1
t1 = 0
for i,value in enumerate(K1):
    print(i)
    print("K1[i]: ", K1[i], "C[i]: ", C_rech[0][i])
    t1 = t1 + K1[i]*C_rech[0][i]
    print("t1: ",t1)

print("Inverse von:", K1[-1])
inverse = pow(K1[-1],-1,mod)
print("ist ", inverse)

t1 = t1 * inverse % mod

print("Tag = ", t1)

# t2
t2 = 0
for i,value in enumerate(K1):
    print(i)
    print("K2[i]: ", K2[i], "C[i]: ", C_rech[0][i+2])
    t2 = t2 + K2[i]*C_rech[0][i+2]
    print("t2: ",t2)

print("Inverse von:", K2[-1])
inverse = pow(K2[-1],-1,mod)
print("ist ", inverse)

t2 = t2 * inverse % mod

print("Tag = ", t2)

# Volles Packet generieren

# we
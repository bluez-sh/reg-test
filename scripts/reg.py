#!/usr/bin/env python3

# Copyright (C) 2021 Swaraj Hota

import sys
import subprocess
import argparse
from loc2addr import *
from reg2addr import *

CFGIF_PATH = 'xilinx-devcfg/devcfg.py'
PARBIT_PATH = 'gen_partial_bitstream.py'
BITMOD_PATH = 'bitmod_init.py'
BIT2BIN_PATH = 'bit2bin.py'

def read_init_values(bitfile, slc):
    bitmod_comm = subprocess.run(['python', BITMOD_PATH, bitfile, slc, '-r'],
            stdout=subprocess.PIPE, text=True)
    if bitmod_comm.returncode != 0:
        print('Error @ ' + BITMOD_PATH)
        exit(1)
    out = bitmod_comm.stdout.strip().split('\n')
    return [int(x.strip().split(' ')[2], 16) for x in out[1:]]

def write_init_values(bitfile, slc, init_dict):
    init_opt = []
    for lut in init_dict:
        if lut == 'A6LUT':
            init_opt.append('--a6lut=' + hex(init_dict[lut]))
        elif lut == 'B6LUT':
            init_opt.append('--b6lut=' + hex(init_dict[lut]))
        elif lut == 'C6LUT':
            init_opt.append('--c6lut=' + hex(init_dict[lut]))
        elif lut == 'D6LUT':
            init_opt.append('--d6lut=' + hex(init_dict[lut]))
        else:
            pass
    bitmod_comm = subprocess.run(['python', BITMOD_PATH, bitfile, slc,
            '--nocrc'] + init_opt)
    if bitmod_comm.returncode != 0:
        print('Error @ ' + BITMOD_PATH)
        exit(1)

def get_init(lut, init_list):
    if lut == 'A6LUT':
        init = init_list[0]
    elif lut == 'B6LUT':
        init = init_list[1]
    elif lut == 'C6LUT':
        init = init_list[2]
    elif lut == 'D6LUT':
        init = init_list[3]
    else:
        pass
    return init

def read_reg_value_from_bitfile(loc_list, reg_index):
    reg_out_bits = len(loc_list) * 2
    regval = 0
    slc_init = dict()
    for (i, loc) in enumerate(loc_list):
        slc, lut = loc.split('/')
        if slc not in slc_init:
            slc_init[slc] = read_init_values('devcfg.out.partial', slc)
        init_list = slc_init[slc]
        init = get_init(lut, init_list)

        o5bit = 1 if init & (1 << reg_index) else 0
        o6bit = 1 if init & (1 << (32 + reg_index)) else 0
        regval |= (o5bit << i)
        regval |= (o6bit << (int(reg_out_bits/2) + i))
    return regval

def write_reg_value_to_bitfile(loc_list, reg_index, regval):
    reg_out_bits = len(loc_list) * 2
    slc_init = dict()
    loc_init = dict(dict())

    for (i, loc) in enumerate(loc_list):
        slc, lut = loc.split('/')
        if slc not in slc_init:
            slc_init[slc] = read_init_values('devcfg.out.partial', slc)
        init_list = slc_init[slc]
        init = get_init(lut, init_list)

        o5bit = 1 if regval & (1 << i) != 0 else 0
        o6bit = 1 if regval & (1 << (int(reg_out_bits/2) + i)) != 0 else 0

        if o5bit == 1:
            init |= (1 << int(reg_index))
        else:
            init &= ~(1 << int(reg_index))

        if o6bit == 1:
            init |= (1 << (32 + int(reg_index)))
        else:
            init &= ~(1 << (32 + int(reg_index)))

        if slc not in loc_init:
            loc_init[slc] = {lut : init}
        else:
            loc_init[slc][lut] = init

    for slc in loc_init:
        write_init_values('devcfg.out.partial', slc, loc_init[slc])

if __name__ == '__main__':

    parser = argparse.ArgumentParser(
            description='Tool to access custom registers in Zynq FPGA using Partial Dynamic Reconfiguration')
    parser.add_argument('reg_name', help='register instance name')
    parser.add_argument('reg_index', help='register index [0-31]')
    parser.add_argument('-w', '--write', help='write hex value to register')
    parser.add_argument('-r', '--read', action='store_true',
            help='read hex value from register')
    #parser.add_argument('-e', '--exec', help='Execute reads/writes from a file')
    args = parser.parse_args()

    if int(args.reg_index) < 0 or int(args.reg_index) > 31:
        print('Valid register index is in the range [0-31]')
        exit(1)

    if not args.read and not args.write:
        print('Please specifiy either read or write option')
        exit(1)

    ## STEP-1: get list of slice locations for the register instance

    loc_list = get_reg2loc(args.reg_name)
    if not loc_list:
        print("Couldn't find silce locations for register: " + args.reg_name)
        exit(1)

    ## STEP-2: get list of frame addresses that configure the register

    # assuming same frames configure all the slices of the register
    addr_list = get_loc2addr(loc_list[0])
    if not addr_list:
        print("Couldn't find frame addresses for register: " + args.reg_name)
        exit(1)

    ## STEP-3: read out the frames (assuming in sequence) from the FPGA

    devc_comm = subprocess.run(['python', CFGIF_PATH, 'read',
            hex(min(addr_list)), str(len(addr_list))], stdout=subprocess.DEVNULL)
    if devc_comm.returncode != 0:
        print('Error @ ' + CFGIF_PATH)
        exit(1)

    ## STEP-4: create a partial bitstream out of the read out frames

    parbit_comm = subprocess.run(['python', PARBIT_PATH, 'devcfg.out'] + \
            [hex(addr) for addr in addr_list])
    if parbit_comm.returncode != 0:
        print('Error @ ' + PARBIT_PATH)
        exit(1)

    ## STEP-5: for read, show the value of the specified register and exit

    if args.read:
        regval = read_reg_value_from_bitfile(loc_list, int(args.reg_index))
        print('0x{:08x}'.format(regval))
        exit(0)

    ## STEP-6: for write, modify the partial bitfile and write back to the FPGA

    if args.write:
        write_reg_value_to_bitfile(loc_list, int(args.reg_index), int(args.write, 16))

        subprocess.run(['python', BIT2BIN_PATH, 'devcfg.out.partial'])

        devc_comm = subprocess.run(['python', CFGIF_PATH, 'write',
                'devcfg.out.partial.bin'], stdout=subprocess.DEVNULL)
        if devc_comm.returncode != 0:
            print('Error @ ' + CFGIF_PATH)
            exit(1)

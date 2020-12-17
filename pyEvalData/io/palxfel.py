#!/usr/bin/env python
# -*- coding: utf-8 -*-

# The MIT License (MIT)
# Copyright (c) 2015-2020 Daniel Schick
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
# OR OTHER DEALINGS IN THE SOFTWARE.

import os
from xrayutilities.io import SPECFile, SPECScan
from xrayutilities.io.helper import xu_open
from xrayutilities import config
import re
import numpy as np

from .spec import Spec

class PalSpecScan(SPECScan):
    """
    Represents a single SPEC scan. This class is usually not called by the
    user directly but used via the SPECFile class.
    """

    def __init__(self, name, scannr, command, date, time, itime, colnames,
                 hoffset, doffset, fname, imopnames, imopvalues, scan_status):
        super().__init__(name, scannr, command, date, time, itime, colnames,
                 hoffset, doffset, fname, imopnames, imopvalues, scan_status)

    def ReadData(self):
        """
        Set the data attribute of the scan class.
        """

        if self.scan_status == "NODATA":
            if config.VERBOSITY >= config.INFO_LOW:
                print("XU.io.SPECScan.ReadData: %s has been aborted - "
                      "no data available!" % self.name)
            self.data = None
            return None

        if not self.has_mca:
            if config.VERBOSITY >= config.INFO_ALL:
                print("XU.io.SPECScan.ReadData: scan %d contains no MCA data"
                      % self.nr)

        with xu_open(self.fname) as self.fid:
            # read header lines
            self.fid.seek(self.hoffset, 0)
            self.header = []
            while self.fid.tell() < self.doffset:
                line = self.fid.readline().decode('ascii', 'ignore')
                self.header.append(line.strip())

            self.fid.seek(self.doffset, 0)

            # create dictionary to hold the data
            if self.has_mca:
                type_desc = {"names": self.colnames + ["MCA"],
                             "formats": len(self.colnames) * [numpy.float32] +
                             [(numpy.uint32, self.mca_channels)]}
            else:
                type_desc = {"names": self.colnames,
                             "formats": len(self.colnames) * [numpy.float32]}

            if config.VERBOSITY >= config.DEBUG:
                print("xu.io.SPECScan.ReadData: type descriptor: %s"
                      % (repr(type_desc)))

            record_list = []  # from this list the record array while be built

            mca_counter = 0
            scan_aborted_flag = False

            for line in self.fid:
                line = line.decode('ascii', 'ignore')
                line = line.strip()
                if not line:
                    continue

                # check if scan is broken
                if (SPEC_scanbroken.findall(line) != [] or
                        scan_aborted_flag):
                    # need to check next line(s) to know if scan is resumed
                    # read until end of comment block or end of file
                    if not scan_aborted_flag:
                        scan_aborted_flag = True
                        self.scan_status = "ABORTED"
                        if config.VERBOSITY >= config.INFO_ALL:
                            print("XU.io.SPECScan.ReadData: %s aborted"
                                  % self.name)
                        continue
                    elif SPEC_scanresumed.match(line):
                        self.scan_status = "OK"
                        scan_aborted_flag = False
                        if config.VERBOSITY >= config.INFO_ALL:
                            print("XU.io.SPECScan.ReadData: %s resumed"
                                  % self.name)
                        continue
                    elif SPEC_commentline.match(line):
                        continue
                    elif SPEC_errorbm20.match(line):
                        print(line)
                        continue
                    else:
                        break

                if SPEC_headerline.match(line) or \
                   SPEC_commentline.match(line):
                    if SPEC_scanresumed.match(line):
                        continue
                    elif SPEC_commentline.match(line):
                        continue
                    else:
                        break

                if mca_counter == 0:
                    # the line is a scalar data line
                    line_list = SPEC_num_value.findall(line)
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECScan.ReadData: %s" % line)
                        print("XU.io.SPECScan.ReadData: read scalar values %s"
                              % repr(line_list))
                    # convert strings to numbers
                    line_list = map(float, line_list)

                    # increment the MCA counter if MCA data is stored
                    if self.has_mca:
                        mca_counter = mca_counter + 1
                        # create a temporary list for the mca data
                        mca_tmp_list = []
                    else:
                        record_list.append(tuple(line_list))
                else:
                    # reading MCA spectrum
                    mca_tmp_list += map(int, SPEC_int_value.findall(line))

                    # increment MCA counter
                    mca_counter = mca_counter + 1
                    # if mca_counter exceeds the number of lines used to store
                    # MCA data: append everything to the record list
                    if mca_counter > self.mca_nof_lines:
                        record_list.append(tuple(list(line_list) +
                                                 [mca_tmp_list]))
                        mca_counter = 0

            # convert the data to numpy arrays
            ncol = len(record_list[0])
            if config.VERBOSITY >= config.INFO_LOW:
                print("XU.io.SPECScan.ReadData: %s: %d %d %d"
                      % (self.name, len(record_list), ncol,
                         len(type_desc["names"])))
            if ncol == len(type_desc["names"]):
                try:
                    self.data = numpy.rec.fromrecords(record_list,
                                                      dtype=type_desc)
                except ValueError:
                    self.scan_status = 'NODATA'
                    print("XU.io.SPECScan.ReadData: %s exception while "
                          "parsing data" % self.name)
            else:
                self.scan_status = 'NODATA'

class PalSpec(Spec):
    """PalSpec"""

    def __init__(self, name, file_path, spec_file_ext='', h5_path='', file_format='{0:07d}_meta.log',
                 scan_list=[], start_scan=0, stop_scan=-1):

        self.file_format = file_format
        self.start_scan = start_scan
        self.scan_list = scan_list

        if len(scan_list):
            self.scan_list = np.array(scan_list)
        elif (start_scan >= 0) and (stop_scan >= start_scan):
            self.scan_list = np.linspace(start_scan, stop_scan)

        super().__init__(name, file_path, spec_file_ext, h5_path)

    def update_spec(self):
        """Update the current spec file if already in memory.
        Otherwise read it and write its content to the hdf5 file.

        """

        try:
            # try if spec file object already exist
            self.spec_file.Update()
        except:
            # load the spec file from disc
            self.spec_file = PalSpecFile(
                self.spec_file_name, path=self.file_path,
                file_format=self.file_format,
                scan_in_list=self.scan_list, start_scan=self.start_scan)
            self.spec_file.Update()

        if not os.path.exists(os.path.join(self.h5_path, self.h5_file_name)) or self.overwrite_h5:
            # save the new or changed spec file content to the hdf5 file
            # if it does not exist
            self.spec_file.Save2HDF5(os.path.join(self.h5_path, self.h5_file_name))

    def addCustomCounters(self, spec_data, scan_num, base_counters):
        """Add custom counters to the spec data array.


        Args:
            specData (ndarray)     : Data array from the spec scan.
            scanNum (int)          : Scan number of the spec scan.
            baseCounters list(str) : List of the base spec and custom counters
                                     from the cList and xCol.

        Returns:
            specData (ndarray): Updated data array from the spec scan.

        """
        return spec_data


# define some uesfull regular expressions
SPEC_time_format = re.compile(r"\d\d:\d\d:\d\d")
SPEC_multi_blank = re.compile(r"\s+")
SPEC_multi_blank2 = re.compile(r"\s\s+")
# denotes a numeric value
SPEC_int_value = re.compile(r"[+-]?\d+")
SPEC_num_value = re.compile(
    r"([+-]?\d*\.*\d*[eE]*[+-]*\d+|[+-]?[Ii][Nn][Ff]|[Nn][Aa][Nn])")
SPEC_dataline = re.compile(r"^[+-]*\d.*")

SPEC_scan = re.compile(r"^#RUN")
SPEC_cmd = re.compile(r"^#CMD")
SPEC_initmoponames = re.compile(r"#MOT")
SPEC_initmopopos = re.compile(r"#VAL")
SPEC_datetime = re.compile(r"^#TIM")
SPEC_exptime = re.compile(r"^#T")
SPEC_nofcols = re.compile(r"^#N")
SPEC_colnames = re.compile(r"^#COL")
SPEC_MCAFormat = re.compile(r"^#@MCA")
SPEC_MCAChannels = re.compile(r"^#@CHANN")
SPEC_headerline = re.compile(r"^#")
SPEC_scanbroken = re.compile(r"#C[a-zA-Z0-9: .]*Scan aborted")
SPEC_scanresumed = re.compile(r"#C[a-zA-Z0-9: .]*Scan resumed")
SPEC_commentline = re.compile(r"#ATT")
SPEC_newheader = re.compile(r"^#E")
SPEC_errorbm20 = re.compile(r"^MI:")
scan_status_flags = ["OK", "NODATA", "ABORTED", "CORRUPTED"]


class PalSpecFile(SPECFile):

    def __init__(self, filename, path='', file_format='{0:07d}_meta.log',
                 scan_in_list=[], start_scan=1):
        """
        SPECFile init routine

        Parameters
        ----------
        filename :  str
            filename of the spec file
        path :      str, optional
            path to the specfile
        """

        self.debug = False
        self.path = path
        self.filename = filename

        # we keep that empty as it has to be updated by parse_folders()
        self.full_filename = ''

        # list holding scan objects
        self.scan_list = []
        self.fid = None
        self.last_offset = 0
        self.scan_in_list = scan_in_list
        if len(self.scan_in_list):
            self.curr_scan_nb = self.scan_in_list[0]
        else:
            self.curr_scan_nb = start_scan

        self.file_format = file_format
        # initially parse the file
        self.init_motor_names_fh = []  # this list will hold the names of the
        # motors saved in initial motor positions given in the file header
        self.init_motor_names_sh = []  # this list will hold the names of the
        # motors saved in initial motor positions given in the scan header
        self.init_motor_names = []  # this list will hold the names of the
        # motors saved in initial motor positions from either the file or
        # scan header

        self.parse_folders()

    def Update(self):
        """
        reread the file and add newly added files. The parsing starts at the
        data offset of the last scan gathered during the last parsing run.
        """

        # reparse the SPEC file
        if config.VERBOSITY >= config.INFO_LOW:
            print("XU.io.SPECFile.Update: reparsing file for new scans ...")
        # mark last found scan as not saved to force reread
        idx = len(self.scan_list)
        if idx > 0:
            lastscan = self.scan_list[idx - 1]
            lastscan.ischanged = True
        self.parse_folders()

    def parse_folders(self):

        data_path = os.path.abspath(self.path)

        if len(self.scan_in_list):
            for scan_nb in self.scan_in_list:
                if scan_nb >= self.curr_scan_nb:
                    self.curr_scan_nb = scan_nb

                    if self.debug:
                        print('Look for scan number {:d}'.format(scan_nb))

                    data_file = os.path.join(
                        data_path,
                        self.file_format.format(scan_nb))

                    if os.path.exists(data_file):
                        self.full_filename = data_file
                        if self.debug:
                            print('Parsing Scan #{:d}'.format(scan_nb))
                        self.Parse()

                        # when parsing is done, we reset everything
                        self.fid = None
                        self.last_offset = 0
                        # self.init_motor_names_fh = []  # this list will hold the names of the
                        # # motors saved in initial motor positions given in the file header
                        # self.init_motor_names_sh = []  # this list will hold the names of the
                        # # motors saved in initial motor positions given in the scan header
                        # self.init_motor_names = []  # this list will hold the names of the

                        # we remeber the last scan number

                    else:
                        if self.debug:
                            print('data file does not exists')
                        break
        else:
            while True:
                scan_nb = self.curr_scan_nb
                if self.debug:
                    print('Look for scan number {:d}'.format(scan_nb))

                data_file = os.path.join(
                    data_path,
                    self.file_format.format(scan_nb))

                if os.path.exists(data_file):
                    self.full_filename = data_file
                    if self.debug:
                        print('Parsing Scan #{:d}'.format(scan_nb))
                    self.Parse()

                    # when parsing is done, we reset everything
                    self.fid = None
                    self.last_offset = 0
                    # self.init_motor_names_fh = []  # this list will hold the names of the
                    # # motors saved in initial motor positions given in the file header
                    # self.init_motor_names_sh = []  # this list will hold the names of the
                    # # motors saved in initial motor positions given in the scan header
                    # self.init_motor_names = []  # this list will hold the names of the

                    # we remeber the last scan number
                    self.curr_scan_nb = self.curr_scan_nb + 1
                else:
                    if self.debug:
                        print('data file does not exists')
                    break

    def Parse(self):
        """
        Parses the file from the starting at last_offset and adding found scans
        to the scan list.
        """
        import numpy
        with xu_open(self.full_filename) as self.fid:
            # move to the last read position in the file
            self.fid.seek(self.last_offset, 0)
            scan_started = False
            scan_has_mca = False
            # list with the motors from whome the initial
            # position is stored.
            init_motor_values = []

            if config.VERBOSITY >= config.DEBUG:
                print('XU.io.SPECFile: start parsing')

            for line in self.fid:
                linelength = len(line)
                line = line.decode('ascii', 'ignore')
                if config.VERBOSITY >= config.DEBUG:
                    print('parsing line: %s' % line)

                # remove trailing and leading blanks from the read line
                line = line.strip()

                # fill the list with the initial motor names in the header
                if SPEC_newheader.match(line):
                    self.init_motor_names_fh = []

                elif SPEC_initmoponames.match(line) and not scan_started:
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found initial motor "
                              "names in file header")
                    line = SPEC_initmoponames.sub("", line)
                    line = line.strip()
                    self.init_motor_names_fh = self.init_motor_names_fh + \
                        SPEC_multi_blank2.split(line)

                # if the line marks the beginning of a new scan
                elif SPEC_scan.match(line) and not scan_started:
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found scan")
                    line_list = SPEC_multi_blank.split(line)
                    scannr = int(line_list[1])
                    # scancmd = "".join(" " + x + " " for x in line_list[2:])
                    scan_started = True
                    scan_has_mca = False
                    scan_header_offset = self.last_offset
                    scan_status = "OK"
                    # define some necessary variables which could be missing in
                    # the scan header
                    itime = numpy.nan
                    time = ''
                    if config.VERBOSITY >= config.INFO_ALL:
                        print("XU.io.SPECFile.Parse: processing scan nr. %d "
                              "..." % scannr)
                    # set the init_motor_names to the ones found in
                    # the file header
                    self.init_motor_names_sh = []
                    self.init_motor_names = self.init_motor_names_fh

                    # if the line contains the date and time information

                elif SPEC_cmd.match(line) and scan_started:
                    line = SPEC_cmd.sub("", line)
                    scancmd = line.strip()
                elif SPEC_datetime.match(line) and scan_started:
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found date and time")
                    # fetch the time from the line data
                    time = SPEC_time_format.findall(line)[0]
                    line = SPEC_time_format.sub("", line)
                    line = SPEC_datetime.sub("", line)
                    date = SPEC_multi_blank.sub(" ", line).strip()

                # if the line contains the integration time
                elif SPEC_exptime.match(line) and scan_started:
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found exposure time")
                    itime = float(SPEC_num_value.findall(line)[0])
                # read the initial motor names in the scan header if present
                elif SPEC_initmoponames.match(line) and scan_started:
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found initial motor "
                              "names in scan header")
                    line = SPEC_initmoponames.sub("", line)
                    line = line.strip()
                    self.init_motor_names_sh = self.init_motor_names_sh + \
                        SPEC_multi_blank2.split(line)
                    self.init_motor_names = self.init_motor_names_sh
                # read the initial motor positions
                elif SPEC_initmopopos.match(line) and scan_started:
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found initial motor "
                              "positions")
                    line = SPEC_initmopopos.sub("", line)
                    line = line.strip()
                    line_list = SPEC_multi_blank.split(line)
                    # sometimes initial motor position are simply empty and
                    # this should not lead to an error
                    try:
                        for value in line_list:
                            init_motor_values.append(float(value))
                    except ValueError:
                        pass

                # if the line contains the column names
                elif SPEC_colnames.match(line) and scan_started:
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found column names")
                    line = SPEC_colnames.sub("", line)
                    line = line.strip()
                    col_names = SPEC_multi_blank.split(line)
                    nofcols = len(col_names)
                    # this is a fix in the case that blanks are allowed in
                    # motor and detector names (only a single balanks is
                    # supported meanwhile)
                    if len(col_names) > nofcols:
                        col_names = SPEC_multi_blank2.split(line)

                elif SPEC_MCAFormat.match(line) and scan_started:
                    mca_col_number = int(SPEC_num_value.findall(
                                         line)[0])
                    scan_has_mca = True

                elif SPEC_MCAChannels.match(line) and scan_started:
                    line_list = SPEC_num_value.findall(line)
                    mca_channels = int(line_list[0])
                    mca_start = int(line_list[1])
                    mca_stop = int(line_list[2])

                elif (SPEC_scanbroken.findall(line) != [] and
                      scan_started):
                    # this is the case when a scan is broken and no data has
                    # been written, but nevertheless a comment is in the file
                    # that tells us that the scan was aborted
                    scan_data_offset = self.last_offset
                    s = PalSpecScan("scan_%i" % (scannr), scannr, scancmd,
                                 date, time, itime, col_names,
                                 scan_header_offset, scan_data_offset,
                                 self.full_filename, self.init_motor_names,
                                 init_motor_values, "NODATA")

                    self.scan_list.append(s)

                    # reset control flags
                    scan_started = False
                    scan_has_mca = False
                    # reset initial motor positions flag
                    init_motor_values = []

                elif SPEC_dataline.match(line) and scan_started:
                    # this is now the real end of the header block. at this
                    # point we know that there is enough information about the
                    # scan

                    # save the data offset
                    scan_data_offset = self.last_offset

                    # create an SPECFile scan object and add it to the scan
                    # list the name of the group consists of the prefix scan
                    # and the number of the scan in the file - this shoule make
                    # it easier to find scans in the HDF5 file.
                    s = PalSpecScan("scan_%i" % (scannr), scannr, scancmd, date,
                                 time, itime, col_names, scan_header_offset,
                                 scan_data_offset, self.full_filename,
                                 self.init_motor_names, init_motor_values,
                                 scan_status)
                    if scan_has_mca:
                        s.SetMCAParams(mca_col_number, mca_channels, mca_start,
                                       mca_stop)

                    self.scan_list.append(s)

                    # reset control flags
                    scan_started = False
                    scan_has_mca = False
                    # reset initial motor positions flag
                    init_motor_values = []

                elif SPEC_scan.match(line) and scan_started:
                    # this should only be the case when there are two
                    # consecutive file headers in the data file without any
                    # data or abort notice of the first scan; first store
                    # current scan as aborted then start new scan parsing
                    s = PalSpecScan("scan_%i" % (scannr), scannr, scancmd,
                                 date, time, itime, col_names,
                                 scan_header_offset, None,
                                 self.full_filename, self.init_motor_names,
                                 init_motor_values, "NODATA")
                    self.scan_list.append(s)

                    # reset control flags
                    scan_started = False
                    scan_has_mca = False
                    # reset initial motor positions flag
                    init_motor_values = []

                    # start parsing of new scan
                    if config.VERBOSITY >= config.DEBUG:
                        print("XU.io.SPECFile.Parse: found scan "
                              "(after aborted scan)")
                    line_list = SPEC_multi_blank.split(line)
                    scannr = int(line_list[1])
                    # scancmd = "".join(" " + x + " " for x in line_list[2:])
                    scan_started = True
                    scan_has_mca = False
                    scan_header_offset = self.last_offset
                    scan_status = "OK"
                    self.init_motor_names_sh = []
                    self.init_motor_names = self.init_motor_names_fh

                # else:
                #     print('cannot read that shit: {:s}'.format(line))
                # store the position of the file pointer
                self.last_offset += linelength

            # if reading of the file is finished store the data offset of the
            # last scan as the last offset for the next parsing run of the file
            self.last_offset = self.scan_list[-1].doffset

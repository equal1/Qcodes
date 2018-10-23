import csv
import json
import os
import textwrap
import time
from functools import partial

import zhinst
import zhinst.utils

from qcodes import Instrument
from qcodes.utils import validators as validators


class ZIHDAWG8(Instrument):
    """
    QCoDeS driver for ZI HDAWG8.
    Requires ZI LabOne software to be installed on the computer running QCoDeS (tested using LabOne (18.05.54618)
    and firmware (53866).
    Furthermore, the Data Server and Web Server must be running and a connection
    between the two must be made.
    """

    def __init__(self, name: str, device_id: str, **kwargs) -> None:
        """
        Create an instance of the instrument.
        Args:
            name (str): The internal QCoDeS name of the instrument
            device_ID (str): The device name as listed in the web server.
        """
        super().__init__(name, **kwargs)
        self.api_level = 6
        (self.daq, self.device, self.props) = zhinst.utils.create_api_session(device_id, self.api_level,
                                                                              required_devtype='HDAWG')
        self.awg_module = self.daq.awgModule()
        self.awg_module.set('awgModule/device', self.device)
        self.awg_module.execute()
        node_tree = self.download_device_node_tree()
        self.create_parameters_from_node_tree(node_tree)

    def enable_channel(self, channel_number):
        """
        Enable a signal output, turns on a blue LED on the device.
        Args:
            channel_number (int): Output channel that should be enabled.
        Returns: None
        """
        self.set('sigouts_{}_on'.format(channel_number), 1)

    def disable_channel(self, channel_number):
        """
        Disable a signal output, turns off a blue LED on the device.
        Args:
            channel_number (int): Output channel that should be disabled.
        Returns: None
        """
        self.set('sigouts_{}_on'.format(channel_number), 0)

    def start_awg(self, awg_number):
        """
        Activate an AWG
        Args:
            awg_number (int): The AWG that should be enabled.
        Returns: None
        """
        self.set('awgs_{}_enable'.format(awg_number), 1)

    def stop_awg(self, awg_number):
        """
        Deactivate an AWG
        Args:
            awg_number (int): The AWG that should be disabled.
        Returns: None
        """
        self.set('awgs_{}_enable'.format(awg_number), 0)

    def waveform_to_csv(self, wave_name, *waveforms):
        """
        Write waveforms to a CSV file in the modules data directory so that it can be referenced and used in a
        sequence program. If more than one waveform is provided they will be played simultaneously but on separate
        outputs.

        Args:
            wave_name: Name of the CSV file, is used by a sequence program.
            waveforms (list): One or more waveforms that are to be written to a CSV file. Note if there are more than
            one waveforms then they have to be of equal length, if not the longer ones will be truncated.

        Returns: None
        """
        data_dir = self.awg_module.getString('awgModule/directory')
        wave_dir = os.path.join(data_dir, "awg", "waves")
        if not os.path.isdir(wave_dir):
            raise Exception("AWG module wave directory {} does not exist or is not a directory".format(wave_dir))
        csv_file = os.path.join(wave_dir, wave_name + '.csv')
        with open(csv_file, "w", newline='') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerows(zip(*waveforms))

    @staticmethod
    def generate_csv_sequence_program(wave_names, channels=None):
        """
        Generates and returns a sequencing program that plays the given waves on the given channels. There has to be a
        CSV file with a corresponding name to a wave in wave_names.
        Args:
            wave_names (list): List of wave names that are to be played.
            channels (list, optional): Channels to play the waveforms on.

        Returns (str): A sequencing program that can be uploaded to the device.
        """
        awg_program = textwrap.dedent("""
            HEADER
            while(true){
                playWave(WAVES);
            }
            """)
        sequence_header = '// generated by {}\n'.format(__name__)
        awg_program = awg_program.replace('HEADER', sequence_header)
        if channels is None:
            argument_string = ('"{}"' * len(wave_names)).replace('""', '", "')
            waves = argument_string.format(*wave_names)
        else:
            argument_string = ('{}, "{}"' * len(wave_names)).replace('}"{', '}", {')
            waves = argument_string.format(*[value for pair in zip(channels, wave_names) for value in pair])
        awg_program = awg_program.replace('WAVES', waves)

        return awg_program

    def upload_sequence_program(self, awg_number, sequence_program):
        """
        Uploads a sequence program to the device equivalent to using the the sequencer tab in the device's gui.
        Args:
            awg_number (int): The AWG that the sequence program will be uploaded to.
            sequence_program (str): A sequence program that should be played on the device.
        Returns (int): 0: Compilation was successful with no warnings.
                       1: Compilation was successful but with warnings.
        """
        self.awg_module.set('awgModule/index', awg_number)
        self.awg_module.set('awgModule/compiler/sourcestring', sequence_program)
        while self.awg_module.getInt('awgModule/compiler/status') == -1:
            time.sleep(0.1)

        if self.awg_module.getInt('awgModule/compiler/status') == 1:
            raise Exception(self.awg_module.getString('awgModule/compiler/statusstring'))
        while self.awg_module.getDouble('awgModule/progress') < 1.0:
            time.sleep(0.1)

        return self.awg_module.getInt('awgModule/compiler/status')

    def upload_waveform(self, awg_number, waveform, index):
        """
        Upload a waveform to the device memory at a given index.
        Node: There needs to be a place holder on the device as this only replaces a data in the device memory and there
              for does not allocate new memory space.
        Args:
            awg_number (int): The AWG where waveform should be uploaded to.
            waveform: An array of floating point values from -1.0 to 1.0, or integers in the range (-32768...+32768)
            index: Index of the waveform that will be replaced. If there are more than 1 waveforms used then the index
                   corresponds to the position of the waveform in the Waveforms sub-tab of the AWG tab in the GUI.
        Returns: None
        """
        self.set('awgs_{}_waveform_index'.format(awg_number), index)
        self.daq.sync()
        self.set('awgs_{}_waveform_data'.format(awg_number), waveform)

    def set_channel_grouping(self, group):
        """
        Set the channel grouping mode of the device.
        Args:
            group (int): 0: Use the outputs in groups of 2. One sequencer program controls 2 outputs.
                         1: Use the outputs in groups of 4. One sequencer program controls 4 outputs.
                         2: Use the outputs in groups of 8. One sequencer program controls 8 outputs.
        Returns: None
        """
        self.set('system_awg_channelgrouping', group)

    def create_parameters_from_node_tree(self, parameters):
        """
        Create QuCoDeS parameters from the device node tree.
        Args:
            parameters (dict): A device node tree.
        Returns: None
        """
        for parameter in parameters.values():
            getter = partial(self._getter, parameter['Node'], parameter['Type']) if 'Read' in parameter[
                'Properties'] else None
            setter = partial(self._setter, parameter['Node'], parameter['Type']) if 'Write' in parameter[
                'Properties'] else None
            options = validators.Enum(*[int(val) for val in parameter['Options'].keys()]) \
                if parameter['Type'] == 'Integer (enumerated)' else None
            parameter_name = self._generate_parameter_name(parameter['Node'])
            self.add_parameter(name=parameter_name,
                               set_cmd=setter,
                               get_cmd=getter,
                               vals=options,
                               docstring=parameter['Description'],
                               unit=parameter['Unit']
                               )

    @staticmethod
    def _generate_parameter_name(node):
        values = node.split('/')
        return '_'.join(values[2:]).lower()

    def download_device_node_tree(self, flags=0):
        """
        Args:
            flags: ziPython.ziListEnum.settingsonly -> 0x08
                        Returns only nodes which are marked as setting
                   ziPython.ziListEnum.streamingonly -> 0x10
                        Returns only streaming nodes
                   ziPython.ziListEnum.subscribedonly -> 0x20
                        Returns only subscribed nodes
                   ziPython.ziListEnum.basechannel -> 0x40
                        Return only one instance of a node in case of multiple channels
                   Or any combination of flags can be used.
        Returns: A dictionary of the device node tree.
        """
        node_tree = self.daq.listNodesJSON('/{}/'.format(self.device), flags)
        return json.loads(node_tree)

    def _setter(self, name, param_type, value):
        if param_type == "Integer (64 bit)" or param_type == 'Integer (enumerated)':
            self.daq.setInt(name, value)
        elif param_type == "Double":
            self.daq.setDouble(name, value)
        elif param_type == "String":
            self.daq.setString(name, value)
        elif param_type == "ZIVectorData":
            self.daq.vectorWrite(name, value)

    def _getter(self, name, param_type):
        if param_type == "Integer (64 bit)" or param_type == 'Integer (enumerated)':
            return self.daq.getInt(name)
        elif param_type == "Double":
            return self.daq.getDouble(name)
        elif param_type == "String":
            return self.daq.getString(name)
        elif param_type == "ZIVectorData":
            return self.daq.vectorRead(name)

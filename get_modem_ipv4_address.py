# Included with Python
import argparse
import csv
import json
import logging
import os
import re
import requests
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# External libraries
try:
    import ncm
except ImportError:
    raise SystemExit('Please install the \'ncm\' module - \'python3 -m pip install ncm\' or provide the library locally.')

# If the user has OS environment variables set for API keys, use those; it fails back to API keys
# from a settings file.
try:
    import settings
except ImportError:
    settings = None

VERSION = '1.0.0'


class GetModemIPv4Address:
    """ A class to retrieve modem IDs and current IPv4 addresses for devices in specified groups """

    # APIv2 base url
    apiv2 = 'https://www.cradlepointecm.com/api/v2'

    # Terminal colors
    red = '\033[91m'
    green = '\033[92m'
    yellow = '\033[93m'
    blue = '\033[94m'
    magenta = '\033[95m'
    cyan = '\033[96m'
    white = '\033[97m'
    bold = '\033[1m'
    underline = '\033[4m'
    reset = '\033[0m'

    all_routers = {}

    def __init__(self, group_names=None, group_ids=None, return_all_modems=False, verbose=False, log_level=None):
        """
        Class constructor

        Parameters:
            group_names (list): Optional -> Group names, separated by commas, to use for looking up devices.
            group_ids (list): Optional -> Group IDs, separated by commas, to use for looking up devices.
            return_all_modems (bool): Optional -> When True, include modems with no IPv4 address in the CSV output.
                Defaults to False (only modems with an IPv4 address are included).
            verbose (bool): Optional -> True enables DEBUG logging; defaults to False.
            log_level (str): Optional -> The log level to use for the script.  Can be DEBUG, INFO, WARNING, ERROR or CRITICAL.
                If not provided, defaults to INFO.

        Returns:
            None.
        """

        # Capture a single timestamp at startup — shared by the log file and CSV output file
        # so both can always be correlated with each other.
        self.timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

        # Process the arguments passed into the constructor
        self.api_keys = self._load_api_keys()
        self.apiv2_headers = {
            **self.api_keys,
            'Content-Type': 'application/json'
        }
        self.log_level = log_level
        self.verbose = verbose

        self.parse_log_level()

        self.script_name = Path(sys.argv[0]).stem
        self.script_dir = Path(sys.argv[0]).resolve().parent

        # Ensure output directories exist
        self.log_dir = self.script_dir / 'output' / 'logs'
        self.csv_dir = self.script_dir / 'output' / 'csv'
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.csv_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = str(self.log_dir / f'{self.script_name}_{self.timestamp}.log')

        self.setup_logging()

        # Initialize API objects
        # A basic http/s requests object
        self.s = requests.session()
        self.s.headers.update(self.apiv2_headers)

        # Create the NCM library object
        self.ncm_client = ncm.NcmClient(api_keys=self.api_keys)

        # Verify API keys work; no point in running the entire script if authentication fails
        self.verify_api_authentication()

        self.group_names = group_names
        self.group_ids = group_ids
        self.return_all_modems = return_all_modems
    # // END __init__()


    @staticmethod
    def _load_api_keys():
        """
            Load the API keys.  Try from environment variables first and fall
            back to keys loaded from a 'settings' file.
        """

        key_map = {
            'X-CP-API-ID': 'X_CP_API_ID',
            'X-CP-API-KEY': 'X_CP_API_KEY',
            'X-ECM-API-ID': 'X_ECM_API_ID',
            'X-ECM-API-KEY': 'X_ECM_API_KEY'
        }

        api_keys = {}
        missing = []

        for header_key, env_key in key_map.items():
            # Try environment variable first
            value = os.environ.get(env_key)

            # Fall back to settings file
            if not value and settings is not None:
                value = settings.api_keys.get(header_key)

            if not value:
                missing.append(header_key)
            else:
                api_keys[header_key] = value

        if missing:
            raise LogThenSystemExit(
                f'Missing API keys: {", ".join(missing)}\n'
                'Please set them as environment variables or add them to settings.py'
            )

        return api_keys
    # // END _load_api_keys()


    def can_write_to_log_file(self) -> bool:
        """
        Test whether we can create/write to the target log file.

        Parameters:
            None.

        Returns:
            True if possible, False otherwise.
        """

        log_path = Path(self.log_file)
        try:
            # Try to create parent directories if needed
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Try opening in append mode (creates file if missing)
            with log_path.open('a', encoding='utf-8'):
                pass
            return True
        except (PermissionError, OSError) as e:
            logging.warning(
                f'Cannot write to log file \'{log_path}\'\n{e}\nLogging to console only'
                f'{" (including DEBUG)" if self.log_level == 10 else ""}'
            )
            return False
    # // END can_write_to_log_file()


    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Central wrapper for all outbound HTTP requests.  Every call to the Cradlepoint API
        should go through this method so that network-level errors are handled in one place.

        Parameters:
            method (str): Required -> The HTTP verb to use, e.g. 'GET', 'POST', 'PUT', 'DELETE'.
                          The value is case-insensitive.
            url (str): Required -> The fully-qualified URL to request.
            **kwargs: Optional -> Any additional keyword arguments accepted by
                      ``requests.Session.request`` such as:
                          headers (dict)  — extra or override headers for this request only.
                          params  (dict)  — query-string parameters.
                          json    (dict)  — request body serialized as JSON.
                          data    (dict|str|bytes) — raw request body.
                          timeout (float) — per-request timeout in seconds.

        Returns:
            requests.Response — the response object returned by the endpoint.
            The caller is responsible for inspecting ``response.ok`` / ``response.status_code``.

        Raises:
            LogThenSystemExit — if a ``requests.exceptions.ConnectionError`` is raised, meaning
                the host could not be reached.  The error is logged and the program exits with a
                descriptive message advising the user to check their internet connection.
        """

        try:
            return self.s.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError:
            logging.info(
                'Unable to connect to the Cradlepoint API. '
                'Your computer may not have a connection to the internet. '
                'Please check your connection and try again.',
                extra={'file_only': True}
            )
            raise SystemExit(
                'Unable to connect to the Cradlepoint API. '
                'Your computer may not have a connection to the internet. '
                'Please check your connection and try again.'
            )
    # // END _make_request()


    def get_group_id_from_group_name(self, group_name) -> Optional[int]:
        """
        Given a group name, get the group ID.

        Parameters:
            group_name (str): Required -> The group name to get the ID for.

        Returns:
            Group ID.
        """

        url = f'{self.apiv2}/groups/?name={group_name}&fields=id'

        print(f'\nValidating group name \'{group_name}\' ... ', end='', flush=True)

        response = self._make_request('GET', url, headers=self.apiv2_headers)

        if response.ok:
            try:
                data = response.json().get('data')

                if not data:
                    print(f'{self.red}failure{self.reset}')
                    logging.info(
                        f'\nValidating group name \'{group_name}\' ... failure',
                        extra={'file_only': True}
                    )
                    return

                group_id = data[0]['id']

                print(f'{self.green}success{self.reset}')
                logging.info(f'\nValidating group name \'{group_name}\' ... success',
                             extra={'file_only': True})

                return group_id
            except KeyError as e:
                print(f'{self.red}failure{self.reset}')
                logging.debug(f'\nValidating group name \'{group_name}\' ... failure', extra={'file_only': True})
                logging.debug(response.json(), extra={'file_only': True})
        else:
            print(f'{self.red}failure{self.reset}')
            logging.debug(f'\nValidating group name \'{group_name}\' ... failure', extra={'file_only': True})
            logging.debug(response.json(), extra={'file_only': True})
    # // END get_group_id_from_group_name()


    def get_group_name_from_group_id(self, group_id) -> str | None:
        """
        Given a group ID, get the group name.

        Parameters:
            group_id (int): Required -> The group ID to get the name for.

        Returns:
            Group name.
        """

        url = f'{self.apiv2}/groups/{group_id}/?fields=name'

        response = self._make_request('GET', url, headers=self.apiv2_headers)

        if response.ok:
            try:
                group_name = response.json()['name']
                return group_name
            except KeyError as e:
                logging.debug(f'Unable to get the group name for group ID \'{group_id}\'\n{e}')
                logging.debug('Setting group name to \'UNKNOWN\' and continuing ...')
                return 'UNKNOWN'
        else:
            logging.debug(
                f'Group ID \'{group_id}\' was not found (HTTP {response.status_code})')
            return None
    # // END get_group_name_from_group_id()


    def get_routers_in_group_ids(self) -> None:
        """
        Using the group ID, get the following fields for the routers in that group: id,name,serial_number,full_product_name.
            Remember that the NCM library, unlike requests, returns the data instead of a response object.

        Parameters:
            None.

        Returns:
            None.  Adds the router info to the `self.all_routers` dictionary.
        """

        for group_id in self.group_ids:
            logging.info(f'\nGetting devices in the group ID \'{group_id}\'')
            print(f'\nValidating group ID \'{group_id}\' ... ', end='', flush=True)
            group_name = self.get_group_name_from_group_id(group_id)
            if group_name is None:
                print(f'{self.red}failure{self.reset}')
                logging.info(
                    f'\nValidating group ID \'{group_id}\' ... failure',
                    extra={'file_only': True}
                )
                raise LogThenSystemExit(f'Group ID \'{group_id}\' was not found. No devices will be processed.')
            print(f'{self.green}success{self.reset}')
            routers_in_group = self.ncm_client.get_routers_for_group(group_id, fields='id,name,serial_number,full_product_name')

            if len(routers_in_group) == 0:
                raise LogThenSystemExit(f'\tNo devices found in the group!')
            else:
                logging.info(f'Found {len(routers_in_group)} device(s) in the group')
                logging.debug(json.dumps(routers_in_group, indent=4))

            # Add the router and its data to the `all_routers` dictionary
            for router in routers_in_group:
                router_data = {
                    'name': router['name'],
                    'serial_number': router['serial_number'],
                    'full_product_name': router['full_product_name'],
                    'group': group_name,
                    'modems': []
                }

                self.all_routers[router['id']] = router_data
    # // END get_routers_in_group_ids()


    def get_routers_in_group_names(self) -> None:
        """
        Using the group name, get the following fields for the routers in that group: id,name,serial_number,full_product_name.
            Remember that the NCM library, unlike requests, returns the data instead of a response object.

        Parameters:
            None.

        Returns:
            None.  Adds the router info to the `self.all_routers` dictionary.
        """

        for group_name in self.group_names:
            logging.info(f'\nGetting devices in the group named \'{group_name}\'')
            group_id = self.get_group_id_from_group_name(group_name)
            if group_id is None:
                raise LogThenSystemExit(f'Group name \'{group_name}\' was not found. Group names are case sensitive! No devices will be processed.')
            routers_in_group = self.ncm_client.get_routers_for_group(group_id, fields='id,name,serial_number,full_product_name')

            if len(routers_in_group) == 0:
                raise LogThenSystemExit(f'\tNo devices found in the group!')
            else:
                logging.info(f'Found {len(routers_in_group)} device(s) in the group')
                logging.debug(json.dumps(routers_in_group, indent=4))

            # Add the router and its data to the `all_routers` dictionary
            for router in routers_in_group:
                router_data = {
                    'name': router['name'],
                    'serial_number': router['serial_number'],
                    'full_product_name': router['full_product_name'],
                    'group': group_name,
                    'modems': []
                }

                self.all_routers[router['id']] = router_data
    # // END get_routers_in_group_names()


    def compile_modem_data(self):
        """
        For each router, query the net devices endpoint to get modem IDs and current IPv4 addresses.

        Parameters:
            None.

        Returns:
            None.
        """

        logging.info(
            f'\nProcessing {len(self.all_routers)} device(s).  Pulling modem IPv4 address data for each.'
        )

        for router_id, router in self.all_routers.items():
            logging.info(f'Processing device: {router["name"]}')

            # Get modem interfaces for this device (is_asset=True returns modem interfaces)
            net_devices = self.ncm_client.get_net_devices_for_router(router_id=router_id, is_asset=True)

            if not net_devices:
                logging.info(f'\tNo modem interfaces found for device \'{router["name"]}\'')
                continue

            for device in net_devices:
                ipv4 = device.get('ipv4_address', '')

                # Skip modems with no IPv4 address unless --return-all-modems is set
                if not self.return_all_modems and not ipv4:
                    logging.debug(f'\tSkipping modem \'{device.get("name", "unknown")}\' — no IPv4 address')
                    continue

                modem_data = {
                    'modem_id': device.get('id', ''),
                    'modem_name': device.get('name', ''),
                    'ipv4_address': ipv4,
                    'mode': device.get('mode', ''),
                    'connection_state': device.get('connection_state', ''),
                }

                self.all_routers[router_id]['modems'].append(modem_data)

            logging.info(f'\tFound {len(self.all_routers[router_id]["modems"])} modem(s)')
            logging.debug(json.dumps(self.all_routers[router_id]['modems'], indent=4))
    # // END compile_modem_data()


    def parse_log_level(self):
        """
        Parse and validate logging level.  If an explicit level is given and it's valid, use it.  If
            it's invalid, default to WARNING.  If an explicit level is not given, look for the use of `-v`
            and set accordingly.  If neither arguments for logging level are used, default to INFO.

        Parameters:
            None.

        Returns:
            None.
        """

        # Logging is not yet setup, use print statement
        print('Parsing log level and setting up logging')

        valid_levels = {
            'debug': logging.DEBUG,     # 10
            'info': logging.INFO,       # 20
            'warning': logging.WARNING, # 30
            'error': logging.ERROR,     # 40
            'critical': logging.CRITICAL # 50
        }

        if self.log_level is not None:
            level = self.log_level.lower()
            if level in valid_levels:
                self.log_level = valid_levels[level]
            else:
                # Invalid level; fall back to WARNING
                print(f'Warning: Invalid log level \'{self.log_level}\'.  Using WARNING level instead')
                self.log_level = logging.WARNING
        else: # Fallback to -v flag
            if self.verbose:
                self.log_level = logging.DEBUG
            else:
                self.log_level = logging.INFO
    # // END parse_log_level()


    def run(self):
        """
        The program's main entry point
        """

        if self.group_names is not None:
            self.get_routers_in_group_names()

        if self.group_ids is not None:
            self.get_routers_in_group_ids()

        self.compile_modem_data()
        logging.debug(json.dumps(self.all_routers, indent=4))

        self.write_to_csv()
    # // END run()


    def setup_logging(self):
        """
        Configure logging based on parsed arguments.  If you want to suppress the HTTPS calls from `urllib3` for example, use:
            logging.getLogger('urllib3').setLevel(logging.WARNING)

        Parameters:
            None.

        Returns:
            None.
        """

        # Configure root logger for any initial logs such as when we attempt to create the file handler
        logging.basicConfig(
            format='%(message)s'
        )

        # Prepare handlers
        handlers = []

        # File handler (only if writable); if it's not writeable, setup the console at whatever level was selected
        # so that it can include DEBUG if necessary
        if self.can_write_to_log_file():
            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            file_handler.setLevel(self.log_level)
            file_handler.setFormatter(
                logging.Formatter(
                    '%(asctime)s %(levelname)-8s %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
            )
            file_handler.addFilter(StripAnsiFilter())
            file_handler.name = 'file_handler'
            handlers.append(file_handler)
        else:
            # No file logging — already warned in self.can_write_to_log_file()
            pass

        log_handlers = logging.getHandlerNames()

        if 'file_handler' in log_handlers:
            console_level = logging.INFO
        else:
            console_level = self.log_level

        # Console handler (always enabled)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(
            logging.Formatter('%(message)s')
        )
        console_handler.addFilter(ConsoleFilter())
        console_handler.name = 'console_handler'
        handlers.append(console_handler)

        handlers.reverse()  # Put console handler first, file handler second

        # Update the root logger with handlers
        logging.basicConfig(
            format='%(message)s',
            level=self.log_level,
            handlers=handlers,
            force=True  # reset any previous configuration
        )

        # Suppress noisy encoding-detection debug output from charset_normalizer (a requests dependency)
        logging.getLogger('charset_normalizer').setLevel(logging.WARNING)

        logging.info(f'Logging initialized at level \'{logging.getLevelName(self.log_level)}\'')
        logging.info(f'Script version: {VERSION}', extra={'file_only': True})

        if 'file_handler' in log_handlers:
            logging.info(f'Log file: {self.yellow}{self.log_file}{self.reset}')
    # // END setup_logging()


    def verify_api_authentication(self) -> None:
        """
        Make an API call to ensure API keys provided work

        Parameters:
            None.

        Returns:
             None.
        """

        print('\nValidating API keys ... ', end='', flush=True)

        authorization_url = f'{self.apiv2}/products/'
        auth_req = self._make_request('GET', authorization_url, headers=self.apiv2_headers)

        if auth_req.status_code == 200:
            print(f'{self.green}success{self.reset}')
            logging.info('Validating API keys ... success', extra={'file_only': True})
        else:
            print(f'{self.red}failure{self.reset}')
            logging.info('Validating API keys ... failure', extra={'file_only': True})
            message = 'Unable to authenticate using the API keys provided\n'
            message += f'X-CP-API-ID: {self.api_keys["X-CP-API-ID"]}\n'
            message += f'X-CP-API-KEY: {self.api_keys["X-CP-API-KEY"]}\n'
            message += f'X-ECM-API-ID: {self.api_keys["X-ECM-API-ID"]}\n'
            message += f'X-ECM-API-KEY: {self.api_keys["X-ECM-API-KEY"]}\n'
            message += f'Response code: {auth_req.status_code}'

            raise LogThenSystemExit(message)
    # // END verify_api_authentication()


    def write_to_csv(self):
        """
        Write the collected device and modem IPv4 data to a CSV file.  The filename uses the shared
            startup timestamp so it always matches the log file produced in the same run.

        Parameters:
            None.

        Returns:
            None.
        """

        filename = str(self.csv_dir / f'{self.script_name}_{self.timestamp}.csv')

        logging.info(f'\nWriting data to .csv file: {self.yellow}{filename}{self.reset}')

        headers = ['Device Id', 'Device Name', 'Serial Number', 'Product', 'Group',
                    'Modem Id', 'Modem Name', 'Ipv4 Address', 'Mode', 'Connection State']

        rows = []
        for router_id, router_info in self.all_routers.items():
            for modem in router_info['modems']:
                row = [
                    router_id,
                    router_info['name'],
                    router_info['serial_number'],
                    router_info['full_product_name'],
                    router_info['group'],
                    modem['modem_id'],
                    modem['modem_name'],
                    modem['ipv4_address'],
                    modem['mode'],
                    modem['connection_state'],
                ]
                rows.append(row)

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            f.write(f'Script Version,{VERSION}\n')
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        logging.info(f'Wrote {len(rows)} row(s) to {filename}')
    # // END write_to_csv()
# // END class GetModemIPv4Address()


class StripAnsiFilter(logging.Filter):
    """Custom logging filter to strip ANSI color codes from log output."""

    def filter(self, record):
        # Strip ANSI codes from the record's message
        record.msg = re.sub(r'\x1b\[[0-9;]*m', '', str(record.msg))
        record.msg = record.msg.lstrip('\n\r\t ')  # Strip leading newline, return, tab or space
        return True
    # // END filter()
# // END class StripAnsiFilter()


class ConsoleFilter(logging.Filter):
    """
        Filter that blocks messages from the console handler if they originate from `urllib3`
            or 'file_only' is True in extra.
    """

    def __init__(self):
        super().__init__()
        root_logger = logging.getLogger()
        self.file_handler_exists = any(isinstance(handler, logging.FileHandler) for handler in root_logger.handlers)
    # // END __init__()

    def filter(self, record):
        # Block `urllib3` messages from this handler (not written to console)
        if record.name.startswith('urllib3'):
            return False

        # Check if the log call included extra={'file_only': True}
        if getattr(record, 'file_only', False):
            return False  # Block from console
        else:
            if not self.file_handler_exists:
                return True  # Allow debug on console since we have no log file

        return True
    # // END filter()
# // END class ConsoleFilter()


class LogThenSystemExit(SystemExit):
    """
        Subclass SystemExit so I can pass a log message to the SystemExit and have it written to the log file
            instead of just to the console.

        Note: In Python, when you subclass something, the parent class has its own setup logic
            in __init__(). If you don't call super().__init__(), that setup never runs and you
            get a partially initialized object.
    """

    def __init__(self, message, **additional_kwargs):
        super().__init__(message)
        exc_info = additional_kwargs.get('exc_info', None)

        if exc_info:
            logging.exception(message, exc_info=exc_info)
        else:
            logging.error(message)
    # // END __init__()
# // END LogThenSystemExit()


class CustomArgParse(argparse.ArgumentParser):
    """
        Subclass argparse so I can handle unknown args and provide custom feedback to the end user if a
            group name or other argument with spaces is not surrounded in double quotes.

        Note: Pycharm doesn't differentiate between `args` and `*args` and will flag this as
            "Shadows name 'args' from outer scope"
    """

    def __init__(self, *additional_args, **additional_kwargs):
        additional_kwargs.setdefault('allow_abbrev', False)
        super().__init__(*additional_args, **additional_kwargs)
    # // END __init__()

    @staticmethod
    def parse_group_ids(group_ids):
        """
            Argparse will pass the value of the argument as a string unless you specify the data type and the data
                submitted matches.  Since I want to allow for singular or multiple values, cast to str and split
                to return a list.
        """

        _list = str(group_ids).split(',')
        return _list
    # // END parse_group_ids()

    @staticmethod
    def parse_group_names(group_names):
        """
            Argparse will pass the value of the argument as a string unless you specify the data type and the data
                submitted matches.  Since I want to allow for singular or multiple values, cast to str and split
                to return a list.
        """

        _list = group_names.split(',')
        return _list
    # // END parse_group_names()

    def parse_known_args(self, additional_args=None, namespace=None):
        known_args, unknown_args = super().parse_known_args(additional_args, namespace)

        # Handle formatting of known arguments to avoid having to process them in __init__()
        for key, value in vars(known_args).items():
            # Strip extra quotes from some arguments
            if key in ['log_level'] and value is not None:
                setattr(known_args, key, value.strip('"').strip("'"))

        if unknown_args:
            args_list = additional_args if additional_args is not None else sys.argv[1:]

            # Maps long flag -> (argparse dest, short flag)
            flag_dest_map = {
                '--group-names':    ('group_names',    '-g'),
                '--group-ids':      ('group_ids',      '-i'),
                '--log-level':      ('log_level',      '-l'),
            }

            unknown_set    = set(unknown_args)
            current_flag   = None
            flag_fragments = {}
            true_unknown   = []

            for token in args_list:
                matched = None
                for long_flag, (dest, short_flag) in flag_dest_map.items():
                    if token.startswith(long_flag) or (short_flag and token.startswith(short_flag)):
                        matched = long_flag
                        break
                if matched:
                    current_flag = matched
                elif token in unknown_set:
                    if token.startswith('-'):
                        true_unknown.append(token)
                    elif current_flag:
                        flag_fragments.setdefault(current_flag, []).append(token)
                    else:
                        true_unknown.append(token)

            message = ''

            if flag_fragments:
                message += '\nError: the following argument(s) appear to have unquoted spaces:\n\n'
                for flag, fragments in flag_fragments.items():
                    message += f'  {flag}  ->  unexpected tokens: {fragments}\n'

                message += '\nCorrected form(s) — enclose the full value in double quotes:\n'
                for flag, fragments in flag_fragments.items():
                    dest, _ = flag_dest_map[flag]
                    parsed  = getattr(known_args, dest, None)
                    if isinstance(parsed, list):
                        reconstructed = ','.join(str(v) for v in parsed) + ' ' + ' '.join(fragments)
                    elif parsed is not None:
                        reconstructed = str(parsed) + ' ' + ' '.join(fragments)
                    else:
                        reconstructed = ' '.join(fragments)
                    message += f'  {flag}="{reconstructed}"\n'

                message += '\nNote: single quotes are NOT supported!'

            if true_unknown:
                if message:
                    message += '\n'
                message += f'\nError: unrecognized argument(s): {true_unknown}\n'
                message += 'Please check your arguments and try again.\n'
                message += 'Use --help for usage information.'

            if not message:
                message  = f'\nError: unrecognized tokens: {unknown_args}\n'
                message += 'Please check your arguments and try again.'

            raise SystemExit(message)

        return known_args, unknown_args
    # // END parse_known_args()
# // END class CustomArgParse()


if __name__ == '__main__':
    parser = CustomArgParse(
        prog='python3 get_modem_ipv4_address.py',
        description='Get modem IDs and current IPv4 addresses for devices in specified groups.'
    )

    # Add the ArgumentParser version information
    parser.add_argument('-V', '--version', help='The version of the script being run.', action='version',
                        version=VERSION)

    # Add the argument to specify one or more group names
    parser.add_argument('-g', '--group-names',
                        help='Specify a group name to which the devices belong, by name.  This can be a comma separated list of multiple names.',
                        dest='group_names', type=CustomArgParse.parse_group_names)

    # Add the argument to specify one or more group IDs
    parser.add_argument('-i', '--group-ids',
                        help='Specify a group to which the devices belong, by ID.  This can be a comma separated list of multiple IDs.',
                        dest='group_ids', type=CustomArgParse.parse_group_ids)

    # Add the argument to specify logging verbosity using -v
    parser.add_argument('-v', '--verbose', help='Enable debug logging (default: INFO).',
                        dest='verbose', action='store_true')

    # Add the argument to return all modems regardless of IPv4 address
    parser.add_argument('-r', '--return-all-modems',
                        help='Include modems with no IPv4 address in the CSV output (default: excluded).',
                        dest='return_all_modems', action='store_true')

    # Add the argument to specify logging level using -l
    parser.add_argument('-l', '--log-level', help='Explicit log level (overrides -v).',
                        dest='log_level', choices=['debug', 'info', 'warning', 'error', 'critical'])

    args = parser.parse_args()

    if not args.group_names and not args.group_ids:
        print(f'Please provide group names or group IDs.\n')
        raise SystemExit(parser.print_help())

    modem_ipv4_obj = GetModemIPv4Address(
        group_names=args.group_names, group_ids=args.group_ids,
        return_all_modems=args.return_all_modems,
        verbose=args.verbose, log_level=args.log_level
    )

    try:
        modem_ipv4_obj.run()
    except Exception as ex:
        raise SystemExit(f'Caught exception!\nError:\ttype={type(ex)}\n\tmessage={str(ex)}')

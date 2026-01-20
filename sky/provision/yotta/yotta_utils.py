"""Yotta API client."""

import base64
import enum
import json
import os
from typing import Any, Dict, List, Optional, Tuple
import uuid

import requests

from sky import sky_logging
from sky.skylet import constants

logger = sky_logging.init_logger(__name__)

CREDENTIALS_FILE_PATH = os.path.expanduser('~/.yotta/credentials')
# ENDPOINT = "https://api.yottalabs.ai/sdk/api"
ENDPOINT = 'https://api.dev.yottalabs.ai/sdk/api'
API_KEY_HEADER = 'X-API-KEY'

# ============= MOCK MODE FOR TESTING =============
# Set to True to use hardcoded pod data instead of calling Yotta API
MOCK_MODE = True

# Hardcoded pod data for testing (from actual Yotta pod)
MOCK_POD_DATA = {
    'id': 402872365298094821,
    'name': 'sky-test-mock-head',  # Will be overwritten by actual cluster name
    'status': 20,  # Maps to PodStatusEnum.RUNNING (status / 10 = 2, but API returns 20)
    'image': 'yotta-btc-dev-harbor-58.com:8089/dockerhub-public-cache/yottalabsai/pytorch:2.9.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04',
    'gpuType': 'NVIDIA_GeForce_RTX_5090_32G',
    'gpuCount': 1,
    'region': 'us-central-3',
    'sshUser': 'user',
    'sshHost': '8hddab3v.ant3.dev.yottalabs.ai',
    'sshPort': '22',
    'expose': [
        {
            'protocol': 'SSH',
            'port': 22,
            'ingressEnabled': False,
            'host': '8hddab3v.ant3.dev.yottalabs.ai',
            'proxyPort': 30010,
            'privateHost': '172.20.71.176',
            'ingressUrl': '',
            'healthy': True
        },
        {
            'protocol': 'HTTP',
            'port': 8888,
            'ingressEnabled': False,
            'host': '8hddab3v.ant3.dev.yottalabs.ai',
            'proxyPort': 30011,
            'privateHost': '172.20.71.176',
            'ingressUrl': '',
            'healthy': True
        }
    ],
    'podInternalIp': '172.20.71.176',
}
# ============= END MOCK MODE =============

GPU_NAME_MAP = {
    '1x_RTX5090_SECURE': 'NVIDIA_GeForce_RTX_5090_32G',
    '8x_RTX5090_SECURE': 'NVIDIA_GeForce_RTX_5090_32G',
}


class PodStatusEnum(enum.Enum):
    """Pod status."""
    INITIALIZE = 0
    RUNNING = 1
    PAUSING = 2
    PAUSED = 3
    TERMINATING = 4
    TERMINATED = 5
    FAILED = 6

    @classmethod
    def from_api_status(cls, api_status: int) -> 'PodStatusEnum':
        """Convert API status (0, 10, 20, ...) to PodStatusEnum.
        
        Yotta API returns status as multiples of 10 (0, 10, 20, 30, ...)
        but PodStatusEnum uses 0, 1, 2, 3, ...
        """
        # Check if it's already in the correct range
        if api_status <= 6:
            return cls(api_status)
        # Convert from API format (0, 10, 20...) to enum format (0, 1, 2...)
        # Note: API status 20 -> RUNNING (1), etc.
        # Based on the pod data, status=20 means running
        status_map = {
            0: cls.INITIALIZE,
            10: cls.INITIALIZE,  # Creating
            20: cls.RUNNING,
            30: cls.PAUSING,
            40: cls.PAUSED,
            50: cls.TERMINATING,
            60: cls.TERMINATED,
            70: cls.FAILED,
        }
        return status_map.get(api_status, cls.FAILED)


class CloudType(enum.Enum):
    """cloud type."""
    SECURE = 1
    COMMUNITY = 2


def get_key_suffix():
    return str(uuid.uuid4()).replace('-', '')[:8]


def _load_credentials() -> Tuple[str, str]:
    """Reads the credentials file and returns userId and apikey."""
    if not os.path.isfile(CREDENTIALS_FILE_PATH):
        raise FileNotFoundError(
            f'Credentials file not found at {CREDENTIALS_FILE_PATH}')

    try:
        with open(CREDENTIALS_FILE_PATH, 'r') as f:
            credentials = {}
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    credentials[key] = value

        user_id: str = credentials.get('userId', '')
        api_key: str = credentials.get('apikey', '')

        if not user_id or not api_key:
            raise ValueError(
                f'Missing userId or apikey in credentials'
                f' file: {CREDENTIALS_FILE_PATH}. '
                'Please ensure the file contains \'userId=<your_user_id>\' and '
                '\'apikey=<your_api_key>\'.')

        return user_id, api_key
    except Exception as e:
        raise ValueError(
            f'Error reading credentials file: {CREDENTIALS_FILE_PATH}. {e}'
        ) from e


def get_ssh_port(instance):
    # get ssh port example:
    # {"port":22,"proxyPort":30003,"protocol":"SSH",
    # "host":"127.0.0.1","privateHost":"127.0.0.1","healthy":true}
    expose = instance.get('expose', [])
    for port in expose:
        if port.get('protocol') == 'SSH':
            return port
    return None


def raise_yotta_error(response: 'requests.Response') -> None:
    """Raise YottaAPIError if appropriate."""
    status_code = response.status_code
    logger.debug(f'response: {response.status_code} - {response.text}')
    try:
        resp_json = response.json()
    except (KeyError, json.decoder.JSONDecodeError) as e:
        raise YottaAPIError(
            f'Unexpected error. Status code: {status_code} \n {response.text} '
            f'\n {str(e)}', status_code) from e
    if response.ok:
        if resp_json.get('code') != 10000:
            raise YottaAPIError(
                f'Business error: {resp_json.get("message", "Unknown error")}',
                resp_json.get('code', status_code))
        return
    else:
        raise YottaAPIError(
            f'Unexpected error. Status code: {status_code} \n {response.text}',
            status_code)


class YottaAPIError(Exception):

    def __init__(self, message: str, code: int = 400):
        self.code = code
        super().__init__(message)


class YottaClient:
    """Yotta API Client"""

    def __init__(self):
        self.user_id, self.api_key = _load_credentials()
        # Track mock instances by cluster name
        self._mock_instances: Dict[str, Dict[str, Any]] = {}

    def check_api_key(self) -> bool:
        if MOCK_MODE:
            logger.info('[MOCK] Skipping API key check, returning True')
            return True
        url = f'{ENDPOINT}/key/check?userId={self.user_id}'
        logger.debug(f'Checking api key for user {self.user_id}')
        response = requests.get(url, headers={API_KEY_HEADER: self.api_key})
        raise_yotta_error(response)
        check_result = response.json()
        # True if api key is valid
        logger.debug(f'Api key check result: {check_result}')
        return check_result['data']

    def list_instances(self,
                       cluster_name_on_cloud: str) -> Dict[str, Dict[str, Any]]:
        if MOCK_MODE:
            logger.info(f'[MOCK] list_instances for cluster: '
                        f'{cluster_name_on_cloud}')
            # In mock mode, always return the mock pod as the head instance
            # This simulates an existing pod that we want to use
            mock_instance = MOCK_POD_DATA.copy()
            mock_instance['name'] = f'{cluster_name_on_cloud}-head'
            instance_id = str(mock_instance['id'])
            # Convert status to internal format
            mock_instance['_internal_status'] = PodStatusEnum.RUNNING
            # Build port2endpoint mapping
            mock_instance['port2endpoint'] = {}
            for port in mock_instance.get('expose', []):
                mock_instance['port2endpoint'][port['port']] = {
                    'host': port['host'],
                    'privateHost': port.get('privateHost', port['host']),
                    'port': port['proxyPort']
                }
            result = {instance_id: mock_instance}
            logger.info(f'[MOCK] Found {len(result)} instances: {list(result.keys())}')
            return result

        url = f'{ENDPOINT}/compute/list'
        all_records: List[Dict[str, Any]] = []
        request_data = {'name': cluster_name_on_cloud}

        response = requests.post(url,
                                 headers={API_KEY_HEADER: self.api_key},
                                 json=request_data)
        response.raise_for_status()
        response_json = response.json()
        if response_json['code'] != 10000:
            raise ValueError(
                f'API returned an error: {response_json["message"]}')

        records = response_json['data']
        all_records.extend(records)

        unique_records = {}
        for record in all_records:
            unique_records[record['id']] = record
            # Convert API status to PodStatusEnum
            api_status = record.get('status', 0)
            status = PodStatusEnum.from_api_status(api_status)
            # Store the converted status for internal use
            record['_internal_status'] = status
            if status == PodStatusEnum.RUNNING:
                ports = record.get('expose', [])
                record['port2endpoint'] = {}
                for port in ports:
                    # container private port mapping to host public port
                    record['port2endpoint'][port['port']] = {
                        'host': port['host'],
                        'privateHost': port.get('privateHost', port['host']),
                        'port': port['proxyPort']
                    }
        return unique_records

    def launch(self, cluster_name: str, node_type: str, instance_type: str,
               region: str, zone: str, image_name: str,
               ports: Optional[List[int]], public_key: str,
               ssh_user: str) -> str:
        """Launches an instance with the given parameters.

        Converts the instance_type to the Yotta GPU name,
        finds the specs for the
        GPU, and launches the instance.

        Returns:
            instance_id: The instance ID.
        """
        _ = region  # Explicitly mark as unused but keep for API compatibility
        name = f'{cluster_name}-{node_type}'

        if MOCK_MODE:
            # In mock mode, return the hardcoded pod data
            # Since list_instances already returns this pod, we just return the ID
            logger.info(f'[MOCK] launch called for {name} - using existing mock pod')
            instance_id = str(MOCK_POD_DATA['id'])
            logger.info(f'[MOCK] Returning existing instance {instance_id}')
            return instance_id

        gpu_type = GPU_NAME_MAP[instance_type]
        gpu_quantity = int(instance_type.split('_')[0].replace('x', ''))
        cloud_type = instance_type.split('_')[2]
        cloud_type = getattr(CloudType, cloud_type, None)
        # TODO : keep this align with setups in
        # `provision.kuberunetes.instance.py`
        setup_cmd = (
            'prefix_cmd() '
            '{ if [ $(id -u) -ne 0 ]; then echo "sudo"; else echo ""; fi; }; '
            '$(prefix_cmd) apt update;'
            'export DEBIAN_FRONTEND=noninteractive;'
            '$(prefix_cmd) apt install openssh-server rsync curl patch -y;'
            '$(prefix_cmd) mkdir -p /var/run/sshd; '
            '$(prefix_cmd) '
            'sed -i "s/PermitRootLogin prohibit-password/PermitRootLogin yes/" '
            '/etc/ssh/sshd_config; '
            '$(prefix_cmd) sed '
            '"s@session\\s*required\\s*pam_loginuid.so@session optional '
            'pam_loginuid.so@g" -i /etc/pam.d/sshd; '
            'cd /etc/ssh/ && $(prefix_cmd) ssh-keygen -A; '
            '$(prefix_cmd) mkdir -p ~/.ssh; '
            '$(prefix_cmd) chown -R $(whoami) ~/.ssh;'
            '$(prefix_cmd) chmod 700 ~/.ssh; '
            f'$(prefix_cmd) echo "{public_key}" >> ~/.ssh/authorized_keys; '
            '$(prefix_cmd) chmod 644 ~/.ssh/authorized_keys; '
            '$(prefix_cmd) service ssh restart; '
            '$(prefix_cmd) export -p > ~/container_env_var.sh && '
            '$(prefix_cmd) '
            'mv ~/container_env_var.sh /etc/profile.d/container_env_var.sh; '
            '[ $(id -u) -eq 0 ] && echo alias sudo="" >> ~/.bashrc;'
            'sleep infinity')
        # Use base64 to deal with the tricky quoting
        # issues caused by runpod API.
        encoded = base64.b64encode(setup_cmd.encode('utf-8')).decode('utf-8')

        docker_args = (f'bash -c \'echo {encoded} | base64 --decode > init.sh; '
                       f'bash init.sh\'')

        expose = []
        if ports is not None:
            custom_ports_str = [{'port': p, 'protocol': 'TCP'} for p in ports]
            expose.extend(custom_ports_str)

        expose.append({'port': 22, 'protocol': 'SSH'})
        expose.append({
            'port': constants.SKY_REMOTE_RAY_DASHBOARD_PORT,
            'protocol': 'HTTP'
        })
        expose.append({
            'port': constants.SKY_REMOTE_RAY_PORT,
            'protocol': 'HTTP'
        })

        request_data = {
            'name': name,
            'image': image_name,
            'gpuType': gpu_type,
            'gpuCount': gpu_quantity,
            'cloudType': cloud_type.value
                         if cloud_type is not None else CloudType.SECURE.value,
            'region': zone,
            'expose': expose,
            'initializationCommand': docker_args,
            'sshUser': ssh_user,
            'sshPublicKey': public_key,
        }
        url = f'{ENDPOINT}/compute/create'

        response = requests.post(
            url,
            headers={API_KEY_HEADER: self.api_key},
            json=request_data,
        )
        logger.debug(f'response: {response.status_code} - {response.text}')
        raise_yotta_error(response)
        response_json = response.json()
        return response_json['data']

    def terminate_instances(self, instance_id: int):
        """Terminate instances."""
        if not instance_id:
            return
        if MOCK_MODE:
            logger.info(f'[MOCK] terminate_instances called for {instance_id}')
            # Remove from mock instances
            str_id = str(instance_id)
            if str_id in self._mock_instances:
                del self._mock_instances[str_id]
            return {'code': 10000, 'message': 'success'}

        url = f'{ENDPOINT}/compute/action'
        request_data = {'id': instance_id, 'action': 'terminate'}
        response = requests.post(url=url,
                                 headers={API_KEY_HEADER: self.api_key},
                                 json=request_data)
        raise_yotta_error(response)
        return response.json()

    def list_ssh_keys(self):
        """list ssh keys."""
        if MOCK_MODE:
            logger.info('[MOCK] list_ssh_keys called')
            return []
        url = f'{ENDPOINT}/compute/keypair/list'
        response = requests.get(url=url, headers={API_KEY_HEADER: self.api_key})
        raise_yotta_error(response)
        response_json = response.json()
        return response_json['data']

    def get_or_add_ssh_key(self, public_key: str = '') -> Dict[str, str]:
        """Add ssh key if not already added."""
        if MOCK_MODE:
            logger.info('[MOCK] get_or_add_ssh_key called')
            return {'name': 'mock-ssh-key', 'ssh_key': public_key}
        ssh_keys = self.list_ssh_keys()
        for key in ssh_keys:
            if key['publicKey'].strip().split()[:2] == public_key.strip().split(
            )[:2]:
                return {'name': key['nickname'], 'ssh_key': public_key}
        ssh_key_name = 'skypilot-' + get_key_suffix()
        url = f'{ENDPOINT}/compute/create/publicKey'
        request_data = {'nickname': ssh_key_name, 'publicKey': public_key}
        response = requests.post(url=url,
                                 headers={API_KEY_HEADER: self.api_key},
                                 json=request_data)
        raise_yotta_error(response)
        return {'name': ssh_key_name, 'ssh_key': public_key}


yotta_client = YottaClient()

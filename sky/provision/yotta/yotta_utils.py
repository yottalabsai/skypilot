"""FluidStack API client."""

import base64
import enum
import json
import os
from typing import Any, Dict, List, Optional

from sky.skylet import constants
import requests

CREDENTIALS_FILE_PATH = os.path.expanduser('~/.yotta/credentials')
ENDPOINT = "https://console.yottalabs.ai/api"
API_KEY_HEADER = 'X-API-KEY'

GPU_NAME_MAP = {
    '1x_L4_SECURE': 'NVIDIA_L4_24G',
    '2x_L4_SECURE': 'NVIDIA_L4_24G',
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

class CloudType(enum.Enum):
    """cloud type."""
    SECURE_CLOUD = 1
    COMMUNITY = 2


def _load_credentials() -> tuple[str, str]:
    """Reads the credentials file and returns userId and apikey."""
    if not os.path.isfile(CREDENTIALS_FILE_PATH):
        raise FileNotFoundError(f"Credentials file not found at {CREDENTIALS_FILE_PATH}")

    try:
        with open(CREDENTIALS_FILE_PATH, 'r') as f:
            credentials = {}
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    credentials[key] = value
        
        user_id: str = credentials.get('userId')
        api_key: str = credentials.get('apikey')

        if not user_id or not api_key:
            raise ValueError(
                f"Missing userId or apikey in credentials file: {CREDENTIALS_FILE_PATH}. "
                f"Please ensure the file contains 'userId=<your_user_id>' and 'apikey=<your_api_key>'."
            )
        
        return user_id, api_key
    except Exception as e:
        raise ValueError(f"Error reading credentials file: {CREDENTIALS_FILE_PATH}. {e}") from e

def get_ssh_port(instance):
        # get ssh port example: {"port":22,"proxyPort":30003,"protocol":"SSH","host":"127.0.0.1","healthy":true}
        expose = instance.get('expose', [])
        for port in expose:
            if port.get('protocol') == 'SSH':
                return port
        return None

def raise_yotta_error(response: 'requests.Response') -> None:
    """Raise YottaAPIError if appropriate."""
    status_code = response.status_code
    try:
        resp_json = response.json()
    except (KeyError, json.decoder.JSONDecodeError) as e:
        raise YottaAPIError(
            f'Unexpected error. Status code: {status_code} \n {response.text} '
            f'\n {str(e)}',
            status_code)
    if response.ok:
        if resp_json.get('code') != 10000:
            raise YottaAPIError(
                f"Business error: {resp_json.get('message', 'Unknown error')}",
                resp_json.get('code', status_code)
            )
        return

            
class YottaAPIError(Exception):

    def __init__(self, message: str, code: int = 400):
        self.code = code
        super().__init__(message)

class YottaClient:
    """Yotta API Client"""

    def __init__(self):
        self.user_id, self.api_key = _load_credentials()
    
    def check_api_key(self) -> bool:
        # todo: add check api key
        url = f"{ENDPOINT}/key/check?userId={self.user_id}"
        response = requests.get(url, headers={API_KEY_HEADER: self.api_key})
        raise_yotta_error(response)
        check_result = response.json()
        # True if api key is valid
        return check_result['data']

    def list_instances(self, cluster_name_on_cloud: str) -> Dict[str, Dict[str, Any]]: 
        url = f"{ENDPOINT}/pod/list"
        all_records: List[Dict[str, Any]] = []
        request_data = {
            "search": {
                "podName": cluster_name_on_cloud
            },
            "pageNumber": 1,
            "pageSize": 50
        }

        while True:
            response = requests.post(
                url,
                headers={API_KEY_HEADER: self.api_key},
                json=request_data
            )
            response.raise_for_status() 

            response_json = response.json()
            if response_json["code"] != 200:
                raise ValueError(f"API returned an error: {response_json['message']}")

            records = response_json["data"]["records"]
            all_records.extend(records)

            if response_json["data"]["pageNumber"] >= response_json["data"]["totalPage"]:
                break

            request_data["pageNumber"] = response_json["data"]["pageNumber"] + 1

        unique_records = {}
        seen_ids = set()
        for record in all_records:
            if record["id"] not in seen_ids:
                unique_records[record["id"]] = record
                seen_ids.add(record["id"])
                status = PodStatusEnum(record.get('status'))
                if status == PodStatusEnum.RUNNING:
                    ports = record.get('expose', [])
                    record['port2endpoint'] = {}
                    for port in ports:
                        # container private port mapping to host public port
                        record['port2endpoint'][port['port']] = {
                            'host': port['host'],
                            'port': port['proxyPort']
                        }
        return unique_records
        
#query myPods {
#     myself {
#         pods {
#             id  有
#             containerDiskInGb containerVolume
#             containerRegistryAuthId  没有
#             costPerHr  running singleCardPrice*gpuCount+ persistentVolume * persistentVolumePrice + containerVolume*containerVolumePrice
#             desiredStatus  没有
#             dockerArgs 没有
#             dockerId 没有
#             env  List<KeyValuePairDTO> environmentVars;
#             gpuCount  gpuCount
#             imageName   image
#             lastStatusChange  
#             machineId
#             memoryInGb
#             name
#             podType
#             port
#             ports
#             uptimeSeconds
#             vcpuCount
#             volumeInGb
#             volumeMountPath
#             runtime {
#                 ports{
#                     ip
#                     isIpPublic
#                     privatePort
#                     publicPort
#                     type
#                 }
#             }
#             machine {
#                 gpuDisplayName
#             }
#         }
#     }
# }

    def get_gpu(self, gpu_type: str,  gpu_quantity: int, cloud_type: str, region: str) -> Dict[str, Any]:
        """Gets the GPU specs for the given GPU type.
    
        Returns:
            gpu_specs: The GPU specs.
        """
        url = f"{ENDPOINT}/gpu/type/filter"
        cloud_type = getattr(CloudType, cloud_type, None)
        request_data = {
            "gpuType": gpu_type,
            "gpuCount": gpu_quantity,
            "cloudType": cloud_type.value,
            "region": region,
        }
        response = requests.post(url, 
                                 headers={API_KEY_HEADER: self.api_key},
                                 json=request_data)
        raise_yotta_error(response)
        return response.json()

    def launch(self, cluster_name: str, node_type: str, instance_type: str, region: str,
               zone: str, image_name: str,
               ports: Optional[List[int]], public_key: str, ssh_user: str) -> str:
        """Launches an instance with the given parameters.
    
        Converts the instance_type to the Yotta GPU name, finds the specs for the
        GPU, and launches the instance.
    
        Returns:
            instance_id: The instance ID.
        """
        name = f'{cluster_name}-{node_type}'
        gpu_type = GPU_NAME_MAP[instance_type.split('_')[1]]
        gpu_quantity = int(instance_type.split('_')[0].replace('x', ''))
        cloud_type = instance_type.split('_')[2]
        gpu_specs = self.get_gpu(gpu_type, gpu_quantity, cloud_type, zone)
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
            '[ $(id -u) -eq 0 ] && echo alias sudo="" >> ~/.bashrc;sleep infinity')
        # Use base64 to deal with the tricky quoting issues caused by runpod API.
        encoded = base64.b64encode(setup_cmd.encode('utf-8')).decode('utf-8')
    
        docker_args = (f'bash -c \'echo {encoded} | base64 --decode > init.sh; '
                       f'bash init.sh\'')
    
        expose = []
        if ports is not None:
            custom_ports_str = [{'port': p, 'protocol': 'TCP'} for p in ports]
            expose.extend(custom_ports_str)

        expose.append({'port': 22, 'protocol': 'SSH'})
        expose.append({'port': constants.SKY_REMOTE_RAY_DASHBOARD_PORT, 'protocol': 'HTTP'})
        expose.append({'port': constants.SKY_REMOTE_RAY_PORT, 'protocol': 'HTTP'})
    
        request_data = {
            'podName': name,
            'image': image_name,
            'resourceType': 1, # gpu type
            'resourceId': gpu_specs['id'],
            'gpuCount': gpu_quantity,
            'containerVolume': gpu_specs['singleCardContainerVolumeLimit'],
            'cloud_type': cloud_type,
            'region': zone,
            'expose': expose,
            'support_public_ip': True,
            'initializationCommand': docker_args,
            'sshUser':  ssh_user,
            'sshPublicKey': public_key,
        }
        
        url = f'{ENDPOINT}/pod/create'

        response = requests.post(
            url,
            headers={API_KEY_HEADER: self.api_key},
            json=request_data,
        )
        raise_yotta_error(response)       
        return response['data']



    # def create_instance(
    #     self,
    #     instance_type: str = '',
    #     name: str = '',
    #     region: str = '',
    #     ssh_pub_key: str = '',
    #     count: int = 1,
    # ) -> List[str]:
    #     """Launch new instances."""

    #     plans = self.get_plans()
    #     regions = self.list_regions()
    #     gpu_type, gpu_count = instance_type.split('::')
    #     gpu_count = int(gpu_count)

    #     plans = [
    #         plan for plan in plans if plan['gpu_type'] == gpu_type and
    #         gpu_count in plan['gpu_counts'] and region in plan['regions']
    #     ]
    #     if not plans:
    #         raise YottaAPIError(
    #             f'Plan {instance_type} out of stock in region {region}')

    #     ssh_key = self.get_or_add_ssh_key(ssh_pub_key)
    #     default_operating_system = 'ubuntu_22_04_lts_nvidia'
    #     instance_ids = []
    #     for _ in range(count):
    #         body = dict(gpu_type=gpu_type,
    #                     gpu_count=gpu_count,
    #                     region=regions[region],
    #                     operating_system_label=default_operating_system,
    #                     name=name,
    #                     ssh_key=ssh_key['name'])

    #         response = requests.post(ENDPOINT + 'instances',
    #                                  headers={'api-key': self.api_key},
    #                                  json=body)
    #         raise_yotta_error(response)
    #         instance_id = response.json().get('id')
    #         instance_ids.append(instance_id)
    #         time.sleep(1)

    #     return instance_ids

    # def list_ssh_keys(self):
    #     response = requests.get(ENDPOINT + 'ssh_keys',
    #                             headers={'api-key': self.api_key})
    #     raise_yotta_error(response)
    #     return response.json()

    # def get_or_add_ssh_key(self, ssh_pub_key: str = '') -> Dict[str, str]:
    #     """Add ssh key if not already added."""
    #     ssh_keys = self.list_ssh_keys()
    #     for key in ssh_keys:
    #         if key['public_key'].strip().split()[:2] == ssh_pub_key.strip(
    #         ).split()[:2]:
    #             return {'name': key['name'], 'ssh_key': ssh_pub_key}
    #     ssh_key_name = 'skypilot-' + get_key_suffix()
    #     response = requests.post(
    #         ENDPOINT + 'ssh_keys',
    #         headers={'api-key': self.api_key},
    #         json=dict(name=ssh_key_name, public_key=ssh_pub_key),
    #     )
    #     raise_yotta_error(response)
    #     return {'name': ssh_key_name, 'ssh_key': ssh_pub_key}

    # @annotations.lru_cache(scope='global')
    # def list_regions(self):
    #     plans = self.get_plans()

    #     def get_regions(plans: List) -> dict:
    #         """Return a list of regions where the plan is available."""
    #         regions = {}
    #         for plan in plans:
    #             for region in plan.get('regions', []):
    #                 regions[region] = region
    #         return regions

    #     regions = get_regions(plans)
    #     return regions

    def terminate_instances(self, instance_id: str):
        """Terminate instances."""
        if  not instance_id:
            return
        url = f"{ENDPOINT}/pod/action"
        request_data = {
            "pod_ids": [instance_id],
            "action": "terminate"
        }
        response = requests.post(url= url,
                                   headers={API_KEY_HEADER: self.api_key},
                                   json=request_data)
        raise_yotta_error(response)
        return response.json()

    # def stop(self, instance_id: str):
    #     response = requests.put(ENDPOINT + 'instances/' + instance_id + '/stop',
    #                             headers={'api-key': self.api_key})
    #     raise_yotta_error(response)
    #     return response.json()

    # def rename(self, instance_id: str, name: str) -> str:
    #     response = requests.put(
    #         ENDPOINT + f'instances/{instance_id}/rename',
    #         headers={'api-key': self.api_key},
    #         json=dict(new_instance_name=name),
    #     )
    #     raise_yotta_error(response)
    #     return response.json()



yotta_client = YottaClient()
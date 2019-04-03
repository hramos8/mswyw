# Provider module to fetch runtime data for an app from New Relic

import requests
from socket import error as SocketError
import xml.etree.ElementTree as ET
import json
import re

# Get instances: https://rpm.newrelic.com/api/explore/application_instances/list?application_id=nnnnnn
# Metric names: https://rpm.newrelic.com/api/explore/application_instances/names?instance_id=nnnnnnnn&application_id=nnnnnnnn


# These are the values we need in @extra_args
# "nrelic.APPID", "nrelic.APIKEY"
def compute_params(extra_args):
    api_key = extra_args.get("%s.APIKEY" % __name__, "")
    app_id = extra_args.get ("%s.APPID" % __name__,None)
    app_ids = []
    if app_id:
        app_ids.append(app_id)
    else:
        app_names = extra_args.get("%s.APPS" % __name__, "")
        app_ids = _get_app_ids_by_name(app_names, api_key)
    if len(app_ids) == 0:
        raise ValueError("No Apps found under the parameters provided: %s" % app_names)
    result = []
    for app_id in app_ids:
        app_instance_ids_and_language = _get_app_instance_ids_and_language(app_id, api_key)
        app_instance_ids = [id_and_language[0] for id_and_language in app_instance_ids_and_language]
        app_instance_languages = [id_and_language[1] for id_and_language in app_instance_ids_and_language]
        metric_dicts = [_get_app_instance_metrics(app_id, api_key, instance_id) for instance_id in app_instance_ids]
        for instance_id, language, metrics in zip(app_instance_ids, app_instance_languages, metric_dicts):
            # we could cheat and instead of looping we could get for the 1st and assume they are all equal. just for speed.
            metrics["endpoints"] = _get_number_of_endpoints(app_id, api_key, instance_id)
            metrics["_id"]=instance_id
            metrics["_lang"] = language
        result.extend(metric_dicts)
    return result

def _get_number_of_endpoints(app_id, api_key, instance_id):
    url = "https://api.newrelic.com/v2/applications/%s/instances/%s/metrics.xml" % (app_id, instance_id)
    newrelic_result = connect_and_get(url, api_key)
    if newrelic_result.status_code != 200:
        raise ValueError(json.loads(newrelic_result.text)["error"]["title"])
    root = ET.fromstring(newrelic_result.content)
    all_metric_names_as_nodes = root.findall(".//metrics/metric/name")
    all_metric_names = [service_name_as_node.text for service_name_as_node in all_metric_names_as_nodes]
    #print("\n".join(sorted(all_metric_names)))
    web_services = [service_name_as_node.text for service_name_as_node in all_metric_names_as_nodes if service_name_as_node.text.startswith("WebTransaction/")] # WebTransaction/RestWebService/ does not work for SpringBoot
    #print("\n".join(sorted(web_services)))
    return len(web_services)


def _get_app_instance_ids_and_language(app_id, api_key):
    url = "https://api.newrelic.com/v2/applications/%s/instances.json" % app_id
    newrelic_result = connect_and_get(url,api_key)
    if newrelic_result.status_code != 200:
        raise ValueError(json.loads(newrelic_result.text)["error"]["title"])
    json_reply = newrelic_result.json()
    return [[instance["id"],instance["language"]] for instance in json_reply["application_instances"]] # "application_name" would be useful too


def _get_app_instance_metrics(app_id, api_key, instance_id):
    url = "https://api.newrelic.com/v2/applications/%s/instances/%s/metrics/data.xml?names[]=Memory/Physical&names[]=Apdex&names[]=CPU/User/Utilization&names[]=WebTransactionTotalTime&summarize=true" % (app_id,instance_id)
    newrelic_result = connect_and_get(url,api_key)
    root = ET.fromstring(newrelic_result.content)
    memory_usage = root.find(".//metrics/metric/[name='Memory/Physical']/timeslices/timeslice/values/used_bytes_by_host")
    apdex = root.find(".//metrics/metric/[name='Apdex']/timeslices/timeslice/values/score")
    cpu_percent = root.find(".//metrics/metric/[name='CPU/User/Utilization']/timeslices/timeslice/values/percent")
    rpm = root.find(".//metrics/metric/[name='WebTransactionTotalTime']/timeslices/timeslice/values//calls_per_minute")
    return {"mem":int(memory_usage.text), "apdex": float(apdex.text), "cpu": float(cpu_percent.text), "rpm": float(rpm.text)}

def _get_app_ids_by_name(app_name_regex, api_key):
    url = "https://api.newrelic.com/v2/applications.xml"
    newrelic_result = connect_and_get(url, api_key)
    if newrelic_result.status_code != 200:
        raise ValueError(json.loads(newrelic_result.text)["error"]["title"])
    root = ET.fromstring(newrelic_result.content)
    all_application_ids_as_nodes = root.findall(".//applications/application/id")
    all_application_names_as_nodes = root.findall(".//applications/application/name")
    selected_app_ids = [app_id_node.text for app_id_node, app_name_node in zip(all_application_ids_as_nodes,all_application_names_as_nodes) if re.search(app_name_regex, app_name_node.text)]
    return selected_app_ids


TIMEOUT=4 #seconds
def connect_and_get (url, api_key, verify=True, timeout=TIMEOUT):
    headers = {'X-Api-Key': api_key}
    return _get(url, headers=headers, verify=verify, timeout=timeout)

def _get (url, headers={}, verify=True, timeout=TIMEOUT):
    try:
        return requests.get(url, headers=headers, verify=verify, timeout=timeout)
    except requests.exceptions.ConnectionError as ce:
        raise ValueError("Connection error opening %s" % url)
    except SocketError as se:
        raise ValueError("Socket error opening %s" % url)
    except requests.exceptions.ReadTimeout as rt:
        raise ValueError("Read timeout opening %s" % url)
    except requests.exceptions.ChunkedEncodingError as cee:
        raise ValueError("Encoding error opening %s" % url)

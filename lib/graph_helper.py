from requests_oauthlib import OAuth2Session
from lib.shell_helper import MsFolderInfo, MsFileInfo
from lib.log import Logger
import json
import os
import pprint


class MsGraphClient:

  graph_url = 'https://graph.microsoft.com/v1.0'

  def __init__(self, token):
    self.token = token
    self.logger = Logger(None, 4)

  def __init__(self, token, logger):
    self.token = token
    self.logger = logger

  def set_logger(self, logger):
    self.logger = logger

  def get_user(self):
    graph_client = OAuth2Session(token=self.token)
    # Send GET to /me
    user = graph_client.get('{0}/me'.format(MsGraphClient.graph_url))
    # Return the JSON result
    return user.json()

  def get_calendar_events(self):
    graph_client = OAuth2Session(token=self.token)

    # Configure query parameters to
    # modify the results
    query_params = {
        '$select': 'subject,organizer,start,end',
        '$orderby': 'createdDateTime DESC'
    }

    # Send GET to /me/events
    events = graph_client.get(
        '{0}/me/events'.format(MsGraphClient.graph_url), params=query_params)
    # Return the JSON result
    return events.json()

  def get_ms_response_for_children_folder_path(self, folder_path):
    """ Get response value of ms graph for getting children info of a onedrive folder
    """
    graph_client = OAuth2Session(token=self.token)

    if folder_path == '':
      fp = '{0}/me/drive/root/children'.format(MsGraphClient.graph_url)
    else:
      fp = '{0}/me/drive/root:/{1}:/children'.format(
          MsGraphClient.graph_url, folder_path)

    ms_response = graph_client.get(fp)

    if 'error' in ms_response:
      return None
    else:
      if "@odata.nextLink" in ms_response.json():
        next_link = ms_response.json()["@odata.nextLink"]
      else:
        next_link = None

      return ms_response.json()['value']

  def download_file_content(self, itemid, local_filename):
    # Inspired from https://gist.github.com/mvpotter/9088499
    graph_client = OAuth2Session(token=self.token)
    r = graph_client.get('{0}/me/drive/items/{1}/content'.format(
        MsGraphClient.graph_url, itemid
    ), stream=True)
    with open(local_filename, 'wb') as f:
      for chunk in r.iter_content(chunk_size=1024):
        if chunk:  # filter out keep-alive new chunks
          f.write(chunk)
          f.flush()
    return 1

  def raw_command(self, cmd):
    graph_client = OAuth2Session(token=self.token)
    result = graph_client.get("{0}{1}".format(
        MsGraphClient.graph_url, cmd
    ))
    return result

  def put_file_content(self, dst_folder, src_file):
    graph_client = OAuth2Session(token=self.token)
    self.logger.log(
        "Start put_file_content('{0}','{1}')".format(
            dst_folder, src_file), 4)
    file_name = src_file.split("/").pop()
    # For file size < 4Mb
    if 1 == 0:
      url = '{0}/me/drive/root:/{1}/{2}:/content'.format(
          MsGraphClient.graph_url,
          dst_folder,
          file_name
      )
      headers = {
          # 'Content-Type' : 'text/plain'
          'Content-Type': 'application/octet-stream'
      }
      print("url put file = {}".format(url))
      r = graph_client.put(
          url,
          data=open(src_file, 'rb'),
          headers=headers)

    # For file size > 4 Mb
    # https://docs.microsoft.com/fr-fr/graph/api/driveitem-createuploadsession?view=graph-rest-1.0
    url = '{0}/me/drive/root:/{1}/{2}:/createUploadSession'.format(
        MsGraphClient.graph_url,
        dst_folder,
        file_name
    )
    data = {
        "item": {
            "@odata.type": "microsoft.graph.driveItemUploadableProperties",
            "@microsoft.graph.conflictBehavior": "replace"
        }
    }

    # Initiate upload session
    data_json = json.dumps(data)
    r1 = graph_client.post(
        url,
        headers={
            'Content-Type': 'application/json'
        },
        data=data_json
    )
    r1_json = r1.json()
    uurl = r1_json["uploadUrl"]

    # Upload parts of file
    total_size = os.path.getsize(src_file)
    print("total_size = {0:,}".format(total_size))

    CHUNK_SIZE = 1048576 * 20  # 20 MB
    current_start = 0

    if total_size >= current_start + CHUNK_SIZE:
      current_end = current_start + CHUNK_SIZE - 1
    else:
      current_end = total_size - 1
    current_size = current_end - current_start + 1

    stop_reason = "OK"
    with open(src_file, 'rb') as fin:
      i = 0
      while True:
        current_stream = fin.read(current_size)

        if not current_stream:
          stop_reason = "end_of_stream"
          break
        if current_start > total_size:
          stop_reason = "current_size_oversized"
          break
        if i > 200:
          stop_reason = "exceed_number_of_loop"
          break

        self.logger.log_debug(
            "{0} start/end/size/total - {1:>15,}{2:>15,}{3:>15,}{4:>15,}".format(
                i, current_start, current_end, current_size, total_size))

        i = i + 1

        headers = {
            'Content-Length': "{0}".format(current_size),
            'Content-Range': "bytes {0}-{1}/{2}".format(current_start, current_end, total_size)
        }

        current_start = current_end + 1
        if total_size >= current_start + CHUNK_SIZE:
          current_end = current_start + CHUNK_SIZE - 1
        else:
          current_end = total_size - 1
        current_size = current_end - current_start + 1

        r = graph_client.put(
            uurl,
            headers=headers,
            data=current_stream)

        # print("response = {0}".format(r.json()))

    # Close URL
    self.cancel_upload(uurl)

    r = r1
    return r

  def cancel_upload(self, upload_url):
    graph_client = OAuth2Session(token=self.token)

    r = graph_client.delete(upload_url)

    return r

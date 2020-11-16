def load(json_load):
    return _byteify(json_load)


def _byteify(data, ignore_dicts=False):
    '''
    Encodes any unicode data as utf-8
    :param data: A data object from json.load or json.loads
    :param ignore_dicts: Should be true if loading json without a top level dict
    :return: unicode free data
    '''
    if isinstance(data, unicode):  # 2to3: change to bytes in Py3
        return data.encode('utf-8')
    if isinstance(data, list):
        return [_byteify(item, ignore_dicts=True) for item in data]
    if isinstance(data, dict) and not ignore_dicts:
        return {_byteify(key, ignore_dicts=True): _byteify(value, ignore_dicts=True) for key, value in data.items()}
    return data

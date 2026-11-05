from string import Formatter


class RestEndpoint(str):
    def __new__(cls, value: str) -> str:
        obj = str.__new__(cls, value)
        obj._fields = {name for _, name, _, _ in Formatter().parse(value) if name}
        return obj

    def __call__(self, **kwargs: str | int) -> str:
        if missing := self._fields.difference(kwargs):
            raise KeyError(f'Missing: {missing}')

        return self.format(**kwargs)


CRUMB = RestEndpoint('crumbIssuer/api/json')

ITEM = RestEndpoint('{job_path}/api/json?depth={depth}')
ITEM_LAST_BUILD_NUMBER = RestEndpoint('{job_path}/api/json?tree=lastBuild[number],buildable')
ITEMS = RestEndpoint('{folder}/api/json?tree={query}')
ITEM_CONFIG = RestEndpoint('{job_path}/config.xml')
ITEM_BUILD_INFO = RestEndpoint('{job_path}/api/json?tree=buildable,property[parameterDefinitions[name]]')
ITEM_TRIGGER = RestEndpoint('{job_path}/{action}')
QUEUE_ITEM_INFO = RestEndpoint('queue/item/{id}/api/json?tree=id,cancelled,task[name,url]')
QUEUE_CANCEL_ITEM = RestEndpoint('queue/cancelItem?id={id}')
BUILD_STATE = RestEndpoint('{job_path}/{number}/api/json?tree=number,building,result')
BUILD_STOP = RestEndpoint('{job_path}/{number}/stop')
ITEM_BUILDS = RestEndpoint(
    '{job_path}/api/json?tree=builds[number,url,result,building,timestamp,duration]{{0,{limit}}}'
)

QUEUE = RestEndpoint('queue/api/json?depth={depth}')
QUEUE_ITEM = RestEndpoint('queue/item/{id}/api/json?depth={depth}')

NODE = RestEndpoint('computer/{name}/api/json?depth={depth}')
NODES = RestEndpoint('computer/api/json?depth={depth}')

VIEW = RestEndpoint('{view_path}/api/json?depth={depth}')
VIEW_COMPACT = RestEndpoint(
    '{view_path}/api/json?tree=name,url,description,jobs[_class,name,url,color],views[name,url]'
)
VIEWS = RestEndpoint('api/json?tree=views[name,url]')

BUILD = RestEndpoint('{job_path}/{number}/api/json?depth={depth}')
BUILD_CONSOLE_OUTPUT = RestEndpoint('{job_path}/{number}/consoleText')
BUILD_REPLAY = RestEndpoint('{job_path}/{number}/replay')
BUILD_PARAMETERS = RestEndpoint('{job_path}/{number}/api/json?tree=actions[parameters[name,value]]')
BUILD_TEST_REPORT = RestEndpoint('{job_path}/{number}/testReport/api/json?depth={depth}')
BUILD_TEST_REPORT_TREE = RestEndpoint('{job_path}/{number}/testReport/api/json?tree={tree}')
BUILD_ARTIFACT = RestEndpoint('{job_path}/{number}/artifact/{relative_path}')
BUILD_ARTIFACTS = RestEndpoint('{job_path}/{number}/api/json?tree=artifacts[fileName,relativePath,displayPath]')
BUILD_PENDING_INPUTS = RestEndpoint('{job_path}/{number}/wfapi/pendingInputActions')

PLUGIN_LIST = RestEndpoint('pluginManager/api/json?depth={depth}')
PLUGIN_LIST_TREE = RestEndpoint('pluginManager/api/json?tree=plugins[{tree}]')

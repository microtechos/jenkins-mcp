import json

import pytest

from mcp_jenkins.jenkins import Jenkins
from mcp_jenkins.jenkins.compact import compact_items, compact_rows, summarize_config
from mcp_jenkins.jenkins.model.item import Job

FREESTYLE = """<?xml version="1.1" encoding="UTF-8"?>
<project>
  <description>Create &amp; Deploy Build</description>
  <scm class="hudson.plugins.git.GitSCM">
    <userRemoteConfigs><hudson.plugins.git.UserRemoteConfig>
      <url>git@github.com:org/web.git</url><credentialsId>deploy-key</credentialsId>
    </hudson.plugins.git.UserRemoteConfig></userRemoteConfigs>
    <branches><hudson.plugins.git.BranchSpec><name>*/release/production</name></hudson.plugins.git.BranchSpec></branches>
  </scm>
  <jdk>(System)</jdk><triggers/><disabled>false</disabled>
  <builders>
    <hudson.tasks.Shell><command>set -eu
export DEPLOY_TOKEN=s3cr3t
npm install
npm run build:prod</command></hudson.tasks.Shell>
  </builders>
  <publishers/>
  <buildWrappers>
    <hudson.plugins.timestamper.TimestamperBuildWrapper/>
    <com.cloudbees.jenkins.plugins.sshagent.SSHAgentBuildWrapper><credentialIds><string>deploy-key</string></credentialIds></com.cloudbees.jenkins.plugins.sshagent.SSHAgentBuildWrapper>
  </buildWrappers>
</project>"""

MAVEN = """<?xml version="1.1" encoding="UTF-8"?>
<maven2-moduleset>
  <jdk>JDK_25</jdk><disabled>false</disabled>
  <rootModule><groupId>com.pos</groupId><artifactId>retails-server</artifactId></rootModule>
  <goals>clean package -Pbranchretailscommon -DskipTests</goals>
  <mavenName>Maven-3.6.3</mavenName>
  <prebuilders><hudson.tasks.Shell><command>cp a b</command></hudson.tasks.Shell></prebuilders>
  <publishers>
    <hudson.tasks.BuildTrigger><childProjects>90-war-storage</childProjects></hudson.tasks.BuildTrigger>
    <hudson.plugins.parameterizedtrigger.BuildTrigger><configs>
      <hudson.plugins.parameterizedtrigger.BuildTriggerConfig><projects>../../Shared-Tomcat-Deployment</projects></hudson.plugins.parameterizedtrigger.BuildTriggerConfig>
    </configs></hudson.plugins.parameterizedtrigger.BuildTrigger>
  </publishers>
</maven2-moduleset>"""


def job(name, color='blue', cls='hudson.model.FreeStyleProject'):
    return Job(fullname=name, color=color, name=name.rsplit('/', 1)[-1], url='https://x/' + name, class_=cls)


class TestCompactItems:
    def test_default_projection(self):
        assert compact_items([job('a/b')]) == [{'fullname': 'a/b', 'kind': 'FreeStyleProject', 'color': 'blue'}]

    def test_much_smaller_than_the_full_dump(self):
        items = [job(f'Folder/sub/job-{i}') for i in range(50)]

        compact = json.dumps(compact_items(items))
        full = json.dumps([i.model_dump(exclude_none=True) for i in items])

        assert len(compact) < len(full) * 0.6

    @pytest.mark.parametrize('limit', [0, -5])
    def test_limit_is_clamped_to_at_least_one(self, limit):
        assert len(compact_items([job('a'), job('b')], limit=limit)) == 2  # 1 row + marker

    def test_limit_is_clamped_to_the_maximum(self):
        rows = compact_items([job(f'j{i}') for i in range(1200)], limit=10**6)

        assert len(rows) == 1001
        assert rows[-1]['total'] == 1200

    def test_no_marker_when_everything_fits(self):
        assert 'truncated' not in json.dumps(compact_items([job('a')], limit=5))

    def test_compact_rows_caps(self):
        rows = compact_rows([{'n': i} for i in range(4)], limit=3)

        assert rows[:3] == [{'n': 0}, {'n': 1}, {'n': 2}]
        assert rows[3]['truncated'] is True


class TestSummarizeConfig:
    def test_freestyle_summary_has_the_facts_and_no_secrets(self):
        s = summarize_config(FREESTYLE)

        assert s['kind'] == 'project'
        assert s['disabled'] is False
        assert s['scm'] == {'urls': ['git@github.com:org/web.git'], 'branches': ['*/release/production']}
        assert s['steps'][0]['phase'] == 'builders'
        assert 'npm run build:prod' in s['steps'][0]['command']
        assert 's3cr3t' not in json.dumps(s)
        assert 'deploy-key' not in json.dumps(s)
        assert s['wrappers'] == ['TimestamperBuildWrapper', 'SSHAgentBuildWrapper']
        assert 'jdk' not in s

    def test_maven_summary_follows_downstream_jobs(self):
        s = summarize_config(MAVEN)

        assert s['module'] == 'com.pos:retails-server'
        assert s['goals'].startswith('clean package')
        assert s['jdk'] == 'JDK_25'
        assert s['downstream'] == ['90-war-storage', '../../Shared-Tomcat-Deployment']
        assert s['steps'] == [{'phase': 'prebuilders', 'type': 'Shell', 'command': 'cp a b'}]

    def test_long_command_is_clipped(self):
        shell = f'<hudson.tasks.Shell><command>{"x" * 2000}</command></hudson.tasks.Shell>'
        xml = f'<project><builders>{shell}</builders></project>'

        command = summarize_config(xml)['steps'][0]['command']

        assert len(command) < 700
        assert command.endswith('chars)')

    def test_summary_is_much_smaller_than_the_xml(self):
        assert len(json.dumps(summarize_config(FREESTYLE))) < len(FREESTYLE)

    def test_disabled_flag(self):
        assert summarize_config('<project><disabled>true</disabled></project>')['disabled'] is True

    def test_parameters(self):
        xml = (
            '<project><properties><hudson.model.ParametersDefinitionProperty><parameterDefinitions>'
            '<hudson.model.StringParameterDefinition><name>BRANCH</name><defaultValue>main</defaultValue>'
            '</hudson.model.StringParameterDefinition></parameterDefinitions>'
            '</hudson.model.ParametersDefinitionProperty></properties></project>'
        )

        assert summarize_config(xml)['parameters'] == [
            {'name': 'BRANCH', 'type': 'StringParameterDefinition', 'default': 'main'}
        ]


@pytest.fixture(autouse=True)
def mock_session(mocker):
    session = mocker.Mock()
    mocker.patch('mcp_jenkins.jenkins.rest_client.requests.Session', autospec=True, return_value=session)
    return session


def make(mocker, **kwargs: object):
    mocker.patch.object(Jenkins, 'crumb_header', new_callable=mocker.PropertyMock, return_value={})
    return Jenkins(url='https://example.com/', username='u', password='p', **kwargs)


class TestJobsStatus:
    TREE = {
        'jobs': [
            {
                'name': 'Retail',
                'jobs': [
                    {
                        'name': 'a',
                        'color': 'blue',
                        'lastBuild': {
                            'number': 9,
                            'result': 'SUCCESS',
                            'building': False,
                            'timestamp': 5,
                            'duration': 74033,
                        },
                    },
                    {'name': 'b', 'color': 'notbuilt', 'lastBuild': None},
                ],
            },
            {
                'name': 'Other',
                'jobs': [
                    {
                        'name': 'c',
                        'color': 'red',
                        'lastBuild': {
                            'number': 1,
                            'result': 'FAILURE',
                            'building': False,
                            'timestamp': 1,
                            'duration': 1000,
                        },
                    }
                ],
            },
        ]
    }

    def test_one_row_per_job_in_one_request(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: self.TREE)

        rows = make(mocker).get_jobs_status()

        assert mock_session.request.call_count == 1
        assert 'lastBuild[number,result,building,timestamp,duration]' in mock_session.request.call_args.kwargs['url']
        assert [r['job'] for r in rows] == ['Retail/a', 'Retail/b', 'Other/c']
        assert rows[0] == {
            'job': 'Retail/a',
            'color': 'blue',
            'build': 9,
            'result': 'SUCCESS',
            'building': False,
            'durationS': 74,
            'timestamp': 5,
        }
        assert rows[1]['build'] is None

    def test_pattern_filters_by_full_name(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: self.TREE)

        assert [r['job'] for r in make(mocker).get_jobs_status(fullname_pattern='^Retail/')] == ['Retail/a', 'Retail/b']

    def test_allowed_folders_filter(self, mocker, mock_session):
        mock_session.request.return_value = mocker.Mock(json=lambda: self.TREE)

        rows = make(mocker, allowed_folders='Other').get_jobs_status()

        assert [r['job'] for r in rows] == ['Other/c']

    def test_overlong_pattern_is_refused(self, mocker):
        with pytest.raises(ValueError, match='longer than'):
            make(mocker).get_jobs_status(fullname_pattern='a' * 201)

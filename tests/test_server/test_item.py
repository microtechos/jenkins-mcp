import pytest
from fastmcp import Client

from mcp_jenkins.jenkins.model.item import Folder, Job
from mcp_jenkins.server import item, mcp


@pytest.fixture
def mock_jenkins(mocker):
    mock_jenkins = mocker.Mock()

    mocker.patch('mcp_jenkins.server.item.jenkins', return_value=mock_jenkins)

    yield mock_jenkins


@pytest.mark.asyncio
async def test_get_all_items(mock_jenkins, mocker):
    mock_jenkins.get_items.return_value = [
        Job(fullname='job1', color='blue', name='job1', url='1', class_='Job'),
        Folder(fullname='job2', jobs=[], class_='Folder', name='folder', url='1'),
    ]

    assert await item.get_all_items(mocker.Mock()) == [
        {'fullname': 'job1', 'kind': 'Job', 'color': 'blue'},
        {'fullname': 'job2', 'kind': 'Folder'},
    ]


@pytest.mark.asyncio
async def test_get_item(mock_jenkins, mocker):
    mock_jenkins.get_item.return_value = Job(fullname='job1', color='blue', name='job1', url='1', class_='Job')

    assert await item.get_item(mocker.Mock(), fullname='job1') == {
        'class_': 'Job',
        'color': 'blue',
        'fullname': 'job1',
        'name': 'job1',
        'url': '1',
    }


@pytest.mark.asyncio
async def test_get_item_config(mock_jenkins, mocker):
    mock_jenkins.get_item_config.return_value = '<xml>config</xml>'

    assert await item.get_item_config(mocker.Mock(), fullname='job1') == '<xml>config</xml>'


@pytest.mark.asyncio
async def test_query_items(mock_jenkins, mocker):
    mock_jenkins.query_items.return_value = [
        Job(fullname='job1', color='blue', name='job1', url='1', class_='Job'),
    ]

    assert await item.query_items(
        mocker.Mock(),
        class_pattern='.*',
        fullname_pattern='job.*',
        color_pattern='blue',
    ) == [
        {'fullname': 'job1', 'kind': 'Job', 'color': 'blue'},
    ]


@pytest.mark.asyncio
async def test_query_items_accepts_explicit_null(mock_jenkins):
    mock_jenkins.query_items.return_value = []

    async with Client(mcp) as client:
        result = await client.call_tool(
            'query_items',
            {'class_pattern': None, 'fullname_pattern': None, 'color_pattern': None, 'folder_depth': None},
        )

    assert result.is_error is False
    mock_jenkins.query_items.assert_called_once_with(
        class_pattern=None,
        fullname_pattern=None,
        color_pattern=None,
        folder_depth=None,
    )


@pytest.mark.asyncio
async def test_get_item_parameters(mock_jenkins, mocker):
    mock_jenkins.get_item_config.return_value = """
        <project>
          <properties>
            <hudson.model.ParametersDefinitionProperty>
              <parameterDefinitions>
                <hudson.model.StringParameterDefinition>
                  <name>BRANCH</name>
                  <defaultValue>main</defaultValue>
                  <description>Branch to build</description>
                </hudson.model.StringParameterDefinition>
                <hudson.model.BooleanParameterDefinition>
                  <name>DEPLOY</name>
                  <defaultValue>false</defaultValue>
                  <description>Deploy after build</description>
                </hudson.model.BooleanParameterDefinition>
              </parameterDefinitions>
            </hudson.model.ParametersDefinitionProperty>
          </properties>
        </project>
    """

    assert await item.get_item_parameters(mocker.Mock(), fullname='job1') == [
        {
            'name': 'BRANCH',
            'type': 'hudson.model.StringParameterDefinition',
            'defaultValue': 'main',
            'description': 'Branch to build',
        },
        {
            'name': 'DEPLOY',
            'type': 'hudson.model.BooleanParameterDefinition',
            'defaultValue': 'false',
            'description': 'Deploy after build',
        },
    ]

    mock_jenkins.get_item_config.assert_called_once_with(fullname='job1')


@pytest.mark.asyncio
async def test_get_item_parameters_no_params(mock_jenkins, mocker):
    mock_jenkins.get_item_config.return_value = '<project><properties/></project>'

    assert await item.get_item_parameters(mocker.Mock(), fullname='job1') == []


@pytest.mark.asyncio
async def test_get_item_parameters_missing_fields(mock_jenkins, mocker):
    mock_jenkins.get_item_config.return_value = """
        <project>
          <properties>
            <hudson.model.ParametersDefinitionProperty>
              <parameterDefinitions>
                <hudson.model.StringParameterDefinition>
                  <name>TOKEN</name>
                </hudson.model.StringParameterDefinition>
              </parameterDefinitions>
            </hudson.model.ParametersDefinitionProperty>
          </properties>
        </project>
    """

    assert await item.get_item_parameters(mocker.Mock(), fullname='job1') == [
        {
            'name': 'TOKEN',
            'type': 'hudson.model.StringParameterDefinition',
            'defaultValue': '',
            'description': '',
        },
    ]


@pytest.mark.asyncio
async def test_query_items_fields_projection_and_no_nested_children(mock_jenkins, mocker):
    child = Job(fullname='f/job1', color='red', name='job1', url='u1', class_='hudson.model.FreeStyleProject')
    folder = Folder(fullname='f', jobs=[child], class_='Folder', name='f', url='u0')
    mock_jenkins.query_items.return_value = [folder, child]

    rows = await item.query_items(mocker.Mock(), fields=['fullname', 'url'])

    assert rows == [{'fullname': 'f', 'url': 'u0'}, {'fullname': 'f/job1', 'url': 'u1'}]


@pytest.mark.asyncio
async def test_query_items_rejects_unknown_field(mock_jenkins, mocker):
    mock_jenkins.query_items.return_value = []

    with pytest.raises(ValueError, match='Unknown field'):
        await item.query_items(mocker.Mock(), fields=['fullname', 'jobs'])


@pytest.mark.asyncio
async def test_query_items_is_capped_with_a_marker(mock_jenkins, mocker):
    mock_jenkins.query_items.return_value = [
        Job(fullname=f'j{i}', color='blue', name=f'j{i}', url='u', class_='Job') for i in range(5)
    ]

    rows = await item.query_items(mocker.Mock(), limit=2)

    assert [r.get('fullname') for r in rows[:2]] == ['j0', 'j1']
    assert rows[2]['truncated'] is True
    assert (rows[2]['shown'], rows[2]['total']) == (2, 5)


@pytest.mark.asyncio
async def test_get_jobs_status_returns_rows_and_caps(mock_jenkins, mocker):
    mock_jenkins.get_jobs_status.return_value = [{'job': f'j{i}', 'build': i} for i in range(3)]

    rows = await item.get_jobs_status(mocker.Mock(), fullname_pattern='^j', folder_depth=2, limit=2)

    mock_jenkins.get_jobs_status.assert_called_once_with(fullname_pattern='^j', folder_depth=2)
    assert rows[:2] == [{'job': 'j0', 'build': 0}, {'job': 'j1', 'build': 1}]
    assert rows[2]['truncated'] is True


@pytest.mark.asyncio
async def test_get_item_summary_uses_the_config(mock_jenkins, mocker):
    mock_jenkins.get_item_config.return_value = '<project><disabled>true</disabled></project>'

    assert await item.get_item_summary(mocker.Mock(), fullname='j') == {'kind': 'project', 'disabled': True}

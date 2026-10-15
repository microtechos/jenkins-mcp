import pytest

from mcp_jenkins.server import plugin


@pytest.fixture
def mock_jenkins(mocker):
    mock_jenkins = mocker.Mock()

    mocker.patch('mcp_jenkins.server.plugin.jenkins', return_value=mock_jenkins)

    yield mock_jenkins


@pytest.mark.asyncio
async def test_get_all_plugins(mock_jenkins, mocker):
    mock_jenkins.get_plugins.return_value = [
        {'shortName': 'plugin-a', 'version': '1.0'},
        {'shortName': 'plugin-b', 'version': '2.0'},
    ]

    result = await plugin.get_all_plugins(mocker.Mock())
    assert result == [
        {'shortName': 'plugin-a', 'version': '1.0'},
        {'shortName': 'plugin-b', 'version': '2.0'},
    ]


@pytest.mark.asyncio
async def test_get_plugin(mock_jenkins, mocker):
    mock_jenkins.get_plugin.return_value = {'shortName': 'plugin-a', 'version': '1.0'}

    result = await plugin.get_plugin(mocker.Mock(), short_name='plugin-a')
    assert result == {'shortName': 'plugin-a', 'version': '1.0'}


@pytest.mark.asyncio
async def test_get_plugins_with_problems(mock_jenkins, mocker):
    mock_jenkins.get_plugins_with_problems.return_value = [
        {'shortName': 'plugin-a', 'problem': 'missing_dependency', 'dependency': 'dep-a'}
    ]

    result = await plugin.get_plugins_with_problems(mocker.Mock())
    assert result == [{'shortName': 'plugin-a', 'problem': 'missing_dependency', 'dependency': 'dep-a'}]


@pytest.mark.asyncio
async def test_get_plugins_with_backup(mock_jenkins, mocker):
    mock_jenkins.get_plugins_with_backup.return_value = [
        {'shortName': 'plugin-a', 'backupVersion': '0.9', 'downgradable': True}
    ]

    result = await plugin.get_plugins_with_backup(mocker.Mock())
    assert result == [{'shortName': 'plugin-a', 'backupVersion': '0.9', 'downgradable': True}]


@pytest.mark.asyncio
async def test_get_plugins_with_updates(mock_jenkins, mocker):
    mock_jenkins.get_plugins_with_updates.return_value = [{'shortName': 'plugin-a', 'version': '1.0'}]

    result = await plugin.get_plugins_with_updates(mocker.Mock())
    assert result == [{'shortName': 'plugin-a', 'version': '1.0'}]


@pytest.mark.asyncio
async def test_get_plugin_dependency_graph(mock_jenkins, mocker):
    mock_jenkins.get_plugin_dependency_graph.return_value = {
        'nodes': [
            {'id': 'plugin-a', 'label': 'plugin-a\n(1.0)', 'status': 'installed'},
            {'id': 'dep-a', 'label': 'dep-a\n(1.0)', 'status': 'installed'},
        ],
        'edges': [{'from': 'plugin-a', 'to': 'dep-a'}],
    }

    result = await plugin.get_plugin_dependency_graph(mocker.Mock(), short_name='plugin-a')
    assert result == {
        'nodes': [
            {'id': 'plugin-a', 'label': 'plugin-a\n(1.0)', 'status': 'installed'},
            {'id': 'dep-a', 'label': 'dep-a\n(1.0)', 'status': 'installed'},
        ],
        'edges': [{'from': 'plugin-a', 'to': 'dep-a'}],
    }

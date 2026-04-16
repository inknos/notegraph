Configuration
=============

``notegraph`` reads its settings from a TOML config file and environment
variables.

Config file
-----------

Default location: ``~/.config/notegraph/config.toml``

Override with the global ``--config`` flag::

    notegraph --config /path/to/config.toml fetch ...

If the file does not exist, built-in defaults are used.

Sections
--------

``[jira]``
^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Default
     - Description
   * - ``endpoint``
     - ``""``
     - Jira Cloud hostname (e.g. ``yourorg.atlassian.net``).
   * - ``email``
     - ``""``
     - Jira account email for HTTP Basic auth.
   * - ``token``
     - ``""``
     - Jira API token. Prefer the ``JIRA_TOKEN`` env var.
   * - ``github_field``
     - ``customfield_10875``
     - Jira custom-field ID that may contain a linked GitHub PR URL.
   * - ``jql``
     - ``""``
     - Default JQL query for ``notegraph todo``. Empty means no Jira
       search unless ``--jql`` is passed on the command line.

``[github]``
^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Default
     - Description
   * - ``token``
     - ``""``
     - GitHub personal access token. Prefer the ``GITHUB_TOKEN`` env var.
   * - ``orgs``
     - ``[]``
     - GitHub organisations to search with ``notegraph todo``
       (e.g. ``["containers"]``).
   * - ``repos``
     - ``[]``
     - Specific ``owner/repo`` pairs to search
       (e.g. ``["myorg/tool"]``).

``[logseq]``
^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Default
     - Description
   * - ``graph_dir``
     - ``~/Documents/Logseq/Work/pages``
     - Output directory for note files and ``worktodo.md``.

Environment variables
---------------------

Environment variables override config-file values:

.. list-table::
   :header-rows: 1
   :widths: 25 30 45

   * - Variable
     - Overrides
     - Notes
   * - ``JIRA_TOKEN``
     - ``jira.token``
     - Recommended over storing the token in the config file.
   * - ``JIRA_EMAIL``
     - ``jira.email``
     -
   * - ``JIRA_ENDPOINT``
     - ``jira.endpoint``
     -
   * - ``GITHUB_TOKEN``
     - ``github.token``
     - Recommended over storing the token in the config file.

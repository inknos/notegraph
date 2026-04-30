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

``[vikunja]``
^^^^^^^^^^^^^

Used by ``notegraph todo --vikunja`` (Jira/GitHub → Vikunja). Vikunja **task
titles** are the Jira issue key or GitHub sync slug (not the human summary); the
summary lives in the task body. Task bodies do not include Logseq note files;
use ``todo --sync`` for note triplets.

Tokens may be set here or via environment variables (recommended for secrets).

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Key
     - Default
     - Description
   * - ``base_url``
     - ``http://127.0.0.1:3456``
     - Vikunja server origin (API calls use ``{base_url}/api/v1``).
   * - ``token``
     - ``""``
     - Vikunja API token. Prefer ``VIKUNJA_TOKEN``.
   * - ``github_search_query``
     - ``""``
     - If non-empty, Vikunja sync uses this GitHub ``q`` via
       ``fetch_todo_search``. If empty, sync uses ``[github].orgs`` and
       ``[github].repos`` with the same queries as ``notegraph todo``.
   * - ``github_project_template``
     - ``"GitHub"``
     - Vikunja **project title** for GitHub tasks. Supports ``str.format``
       placeholders (``repo``, ``org``, ``repo_name``) if you want
       per-repo projects, e.g. ``"{repo}"``.
   * - ``jira_project_template``
     - ``"JIRA"``
     - Vikunja **project title** for Jira tasks. Supports ``str.format``
       placeholders (``project_key``, ``issue_key``) if you want
       per-project projects, e.g. ``"{project_key}"``.

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
   * - ``VIKUNJA_TOKEN``
     - ``vikunja.token``
     - Recommended over storing the token in the config file.
   * - ``VIKUNJA_BASE_URL``
     - ``vikunja.base_url``
     -

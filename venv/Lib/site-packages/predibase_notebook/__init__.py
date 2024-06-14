# flake8: noqa
from typing import Any

from IPython import get_ipython
from IPython.display import Javascript
from predibase_notebook.env import _setup_pql_notebook

_HIGHLIGHT_JS = r"""
require(["codemirror/lib/codemirror"]);
function set(str) {
    var obj = {}, words = str.split(" ");
    for (var i = 0; i < words.length; ++i) obj[words[i]] = true;
    return obj;
  }
var pql_keywords = "given predict evaluate explain with";
var pql_functions = "confidence explanation using";
CodeMirror.defineMIME("text/x-pql", {
    name: "sql",
    keywords: set(pql_keywords + " add after all alter analyze and anti archive array as asc at between bucket buckets by cache cascade case cast change clear cluster clustered codegen collection column columns comment commit compact compactions compute concatenate cost create cross cube current current_date current_timestamp database databases data dbproperties defined delete delimited deny desc describe dfs directories distinct distribute drop else end escaped except exchange exists explain export extended external false fields fileformat first following for format formatted from full function functions global grant group grouping having if ignore import in index indexes inner inpath inputformat insert intersect interval into is items join keys last lateral lazy left like limit lines list load local location lock locks logical macro map minus msck natural no not null nulls of on optimize option options or order out outer outputformat over overwrite partition partitioned partitions percent preceding principals purge range recordreader recordwriter recover reduce refresh regexp rename repair replace reset restrict revoke right rlike role roles rollback rollup row rows schema schemas select semi separated serde serdeproperties set sets show skewed sort sorted start statistics stored stratify struct table tables tablesample tblproperties temp temporary terminated then to touch transaction transactions transform true truncate unarchive unbounded uncache union unlock unset use using values view when where window with"),
    builtin: set(pql_functions + " date datetime tinyint smallint int bigint boolean float double string binary timestamp decimal array map struct uniontype delimited serde sequencefile textfile rcfile inputformat outputformat"),
    atoms: set("false true null"),
    operatorChars: /^[*\/+\-%<>!=~&|^]/,
    dateSQL: set("time"),
    support: set("ODBCdotTable doubleQuote zerolessFloat")
  });

CodeMirror.modeInfo.push( {
            name: "PQL",
            mime: "text/x-pql",
            mode: "sql"
          } );

require(['notebook/js/codecell'], function(codecell) {
    codecell.CodeCell.options_default.highlight_modes['magic_text/x-pql'] = {'reg':[/%%pql/]} ;
    Jupyter.notebook.events.on('kernel_ready.Kernel', function(){
    Jupyter.notebook.get_cells().map(function(cell){
        if (cell.cell_type == 'code'){ cell.auto_highlight(); } }) ;
    });
  });
"""


def load_ipython_extension(ip: Any) -> None:
    """Entrypoint for IPython %load_ext."""
    _setup_pql_notebook(ip)


def _jupyter_nbextension_paths():
    return [
        {
            "section": "notebook",
            "src": "nbextension",
            "dest": "predibase_notebook",
            "require": "predibase_notebook/main",
        },
    ]


def setup() -> Any:
    ip = get_ipython()
    _setup_pql_notebook(ip)
    return Javascript(_HIGHLIGHT_JS)

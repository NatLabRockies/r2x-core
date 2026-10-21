> Design proposal for a future graph-based file mapping and parser rule contract.
> No code in this repository implements it.
> See `docs/source/explanations/tabular-processing-roadmap.md` for the step-list parity gates.
> If adopted, these schemas must replace `DataFile` and `Rule` end to end, never coexist.

### File mappings

A file mapping is one list of nodes. `kind` distinguishes `file` from `table`.
Within an application, all node names share one namespace. File names use an
`_input` suffix, and sources refer directly to names, such as
`"source": "generators_input"`. Names must be unique and dependencies acyclic.

A file node declares `relative_fpath` and `reader`. Paths resolve against the
application input root. The reader's `kind` selects `csv`, `hdf5`, or `plexos`,
and its `kwargs` describe the input layout or XML selection. A table node
instead declares `source` and ordered `steps`.

Expressions use explicit `column` or `literal` operands and named operations
with `args`. Joins refer to other named nodes. Reader options and transformations
remain separate.

### Parser rules

Parser rules are one list. `kind` distinguishes `component`,
`supplemental_attribute`, and `time_series`. Each rule's `source` names a node
in the application mapping. Model names refer to that application's native
component models.

Component and supplemental-attribute rules use these conventions:

- Same-named columns map to declared model fields automatically. Other columns
  are not passed to the model constructor.
- `fields` contains only explicit renames. For example, `{"name": "region_id"}`
  maps the `region_id` column to the model's `name` field. These entries override
  automatic mapping for those fields.
- `references` resolves component-valued fields before model validation. Those
  fields do not also receive automatic mappings or entries in `fields`.
- Reference and time-series owner keys default to `name`. Target models and
  source columns remain explicit.
- Missing columns leave model defaults in effect. Present nulls and zeros are
  preserved. Missing required fields and missing or ambiguous references are
  errors.

Time-series units, resolution, sample counts, metadata, and
supplemental-attribute attachment targets remain explicit.

### reeds/file_mapping.json

```json
[
  {
    "kind": "file",
    "name": "hierarchy_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "inputs_case/hierarchy.csv"
  },
  {
    "kind": "file",
    "name": "load_input",
    "reader": {
      "kind": "hdf5",
      "kwargs": {
        "additional_keys": [
          "index_0"
        ],
        "column_name_mapping": {
          "index_0": "solve_year"
        },
        "columns_key": "columns",
        "data_key": "data",
        "datetime_column_name": "timestamp",
        "datetime_key": "index_1",
        "strip_timezone": true
      }
    },
    "relative_fpath": "inputs_case/load.h5"
  },
  {
    "kind": "file",
    "name": "capacity_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "outputs/tran_cap_energy.csv"
  },
  {
    "kind": "file",
    "name": "distance_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "inputs_case/transmission_distance.csv"
  },
  {
    "kind": "file",
    "name": "generators_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "inputs/generators.csv"
  },
  {
    "kind": "table",
    "name": "regions",
    "source": "hierarchy_input",
    "steps": [
      {
        "columns": {
          "cc_region": {
            "column": "ccreg"
          },
          "cendiv": {
            "column": "cendiv"
          },
          "country": {
            "column": "country"
          },
          "h2ptc_region": {
            "column": "h2ptcreg"
          },
          "hurdle_region": {
            "column": "hurdlereg"
          },
          "interconnect": {
            "column": "interconnect"
          },
          "nerc_region": {
            "column": "nercr"
          },
          "region_id": {
            "column": "*r"
          },
          "state": {
            "column": "st"
          },
          "transmission_group": {
            "column": "transgrp"
          },
          "transmission_region": {
            "column": "transreg"
          },
          "usda_region": {
            "column": "usda_region"
          }
        },
        "op": "select"
      }
    ]
  },
  {
    "kind": "table",
    "name": "load_values",
    "source": "load_input",
    "steps": [
      {
        "columns": {
          "weather_year": {
            "args": [
              {
                "column": "timestamp"
              }
            ],
            "op": "year"
          }
        },
        "op": "with_columns"
      },
      {
        "op": "filter",
        "predicate": {
          "args": [
            {
              "args": [
                {
                  "column": "solve_year"
                },
                {
                  "literal": 2032
                }
              ],
              "op": "eq"
            },
            {
              "args": [
                {
                  "column": "weather_year"
                },
                {
                  "literal": 2012
                }
              ],
              "op": "eq"
            }
          ],
          "op": "and"
        }
      },
      {
        "index": [
          "timestamp",
          "solve_year",
          "weather_year"
        ],
        "op": "unpivot",
        "value_name": "power_mw",
        "variable_name": "region_id"
      }
    ]
  },
  {
    "kind": "table",
    "name": "demands",
    "source": "load_values",
    "steps": [
      {
        "agg": {
          "max_active_power": {
            "args": [
              {
                "column": "power_mw"
              }
            ],
            "op": "max"
          }
        },
        "by": [
          "region_id",
          "solve_year",
          "weather_year"
        ],
        "op": "group_by"
      },
      {
        "columns": {
          "name": {
            "args": [
              {
                "column": "region_id"
              },
              {
                "literal": "_load"
              }
            ],
            "op": "concat_str"
          }
        },
        "op": "with_columns"
      }
    ]
  },
  {
    "kind": "table",
    "name": "demand_profiles",
    "source": "load_values",
    "steps": [
      {
        "how": "left",
        "on": [
          "region_id",
          "solve_year",
          "weather_year"
        ],
        "op": "join",
        "source": "demands",
        "validate": "m:1"
      },
      {
        "columns": {
          "owner_name": {
            "column": "name"
          },
          "power_mw": {
            "column": "power_mw"
          },
          "solve_year": {
            "column": "solve_year"
          },
          "timestamp": {
            "column": "timestamp"
          },
          "weather_year": {
            "column": "weather_year"
          }
        },
        "op": "select"
      },
      {
        "by": [
          "owner_name",
          "timestamp"
        ],
        "op": "sort"
      }
    ]
  },
  {
    "kind": "table",
    "name": "capacity",
    "source": "capacity_input",
    "steps": [
      {
        "op": "filter",
        "predicate": {
          "args": [
            {
              "column": "t"
            },
            {
              "literal": 2032
            }
          ],
          "op": "eq"
        }
      },
      {
        "columns": {
          "capacity": {
            "column": "value"
          },
          "from_region": {
            "column": "r"
          },
          "line_type": {
            "args": [
              {
                "column": "trtype"
              }
            ],
            "op": "lowercase"
          },
          "to_region": {
            "column": "rr"
          }
        },
        "op": "select"
      }
    ]
  },
  {
    "kind": "table",
    "name": "reverse_capacity",
    "source": "capacity",
    "steps": [
      {
        "columns": {
          "from_region": {
            "column": "to_region"
          },
          "line_type": {
            "column": "line_type"
          },
          "reverse_capacity": {
            "column": "capacity"
          },
          "to_region": {
            "column": "from_region"
          }
        },
        "op": "select"
      }
    ]
  },
  {
    "kind": "table",
    "name": "distances",
    "source": "distance_input",
    "steps": [
      {
        "columns": {
          "distance_miles": {
            "column": "miles"
          },
          "from_region": {
            "column": "r"
          },
          "to_region": {
            "column": "rr"
          }
        },
        "op": "select"
      }
    ]
  },
  {
    "kind": "table",
    "name": "lines",
    "source": "capacity",
    "steps": [
      {
        "how": "left",
        "on": [
          "from_region",
          "to_region",
          "line_type"
        ],
        "op": "join",
        "source": "reverse_capacity",
        "validate": "m:1"
      },
      {
        "how": "left",
        "on": [
          "from_region",
          "to_region"
        ],
        "op": "join",
        "source": "distances",
        "validate": "m:1"
      },
      {
        "columns": {
          "endpoints": {
            "args": [
              {
                "args": [
                  {
                    "column": "from_region"
                  },
                  {
                    "column": "to_region"
                  }
                ],
                "op": "concat_list"
              }
            ],
            "op": "list_sort"
          },
          "reverse_capacity": {
            "args": [
              {
                "column": "reverse_capacity"
              },
              {
                "column": "capacity"
              }
            ],
            "op": "coalesce"
          }
        },
        "op": "with_columns"
      },
      {
        "columns": {
          "from_to": {
            "args": [
              {
                "args": [
                  {
                    "column": "from_region"
                  },
                  {
                    "column": "to_region"
                  }
                ],
                "op": "le"
              },
              {
                "column": "capacity"
              },
              {
                "column": "reverse_capacity"
              }
            ],
            "op": "when"
          },
          "to_from": {
            "args": [
              {
                "args": [
                  {
                    "column": "from_region"
                  },
                  {
                    "column": "to_region"
                  }
                ],
                "op": "le"
              },
              {
                "column": "reverse_capacity"
              },
              {
                "column": "capacity"
              }
            ],
            "op": "when"
          }
        },
        "op": "with_columns"
      },
      {
        "columns": {
          "distance_miles": {
            "column": "distance_miles"
          },
          "from_region": {
            "args": [
              {
                "column": "endpoints"
              },
              {
                "literal": 0
              }
            ],
            "op": "list_get"
          },
          "from_to": {
            "column": "from_to"
          },
          "line_type": {
            "column": "line_type"
          },
          "to_from": {
            "column": "to_from"
          },
          "to_region": {
            "args": [
              {
                "column": "endpoints"
              },
              {
                "literal": 1
              }
            ],
            "op": "list_get"
          }
        },
        "op": "select"
      },
      {
        "columns": {
          "interface_name": {
            "args": [
              {
                "column": "from_region"
              },
              {
                "literal": "||"
              },
              {
                "column": "to_region"
              }
            ],
            "op": "concat_str"
          },
          "max_active_power": {
            "args": [
              {
                "column": "from_to"
              },
              {
                "column": "to_from"
              }
            ],
            "op": "struct"
          },
          "name": {
            "args": [
              {
                "column": "from_region"
              },
              {
                "literal": "_"
              },
              {
                "column": "to_region"
              },
              {
                "literal": "_"
              },
              {
                "column": "line_type"
              }
            ],
            "op": "concat_str"
          }
        },
        "op": "with_columns"
      },
      {
        "op": "unique",
        "subset": [
          "name",
          "from_region",
          "to_region",
          "from_to",
          "to_from",
          "distance_miles"
        ]
      }
    ]
  },
  {
    "kind": "table",
    "name": "interfaces",
    "source": "lines",
    "steps": [
      {
        "columns": {
          "from_region": {
            "column": "from_region"
          },
          "name": {
            "column": "interface_name"
          },
          "to_region": {
            "column": "to_region"
          }
        },
        "op": "select"
      },
      {
        "op": "unique",
        "subset": [
          "name",
          "from_region",
          "to_region"
        ]
      }
    ]
  },
  {
    "kind": "table",
    "name": "generators",
    "source": "generators_input",
    "steps": [
      {
        "op": "assert",
        "predicate": {
          "args": [
            {
              "column": "capacity"
            },
            {
              "literal": 0
            }
          ],
          "op": "gt"
        }
      },
      {
        "agg": {
          "capacity": {
            "args": [
              {
                "column": "capacity"
              }
            ],
            "op": "sum"
          },
          "fom_cost": {
            "args": [
              {
                "args": [
                  {
                    "args": [
                      {
                        "column": "fom_cost"
                      }
                    ],
                    "op": "is_null"
                  }
                ],
                "op": "any"
              },
              {
                "literal": null
              },
              {
                "args": [
                  {
                    "args": [
                      {
                        "args": [
                          {
                            "column": "capacity"
                          },
                          {
                            "column": "fom_cost"
                          }
                        ],
                        "op": "multiply"
                      }
                    ],
                    "op": "sum"
                  },
                  {
                    "args": [
                      {
                        "column": "capacity"
                      }
                    ],
                    "op": "sum"
                  }
                ],
                "op": "divide"
              }
            ],
            "op": "when"
          },
          "vom_cost": {
            "args": [
              {
                "column": "vom_cost"
              }
            ],
            "op": "mean"
          }
        },
        "by": [
          "region",
          "technology"
        ],
        "op": "group_by"
      },
      {
        "columns": {
          "name": {
            "args": [
              {
                "column": "technology"
              },
              {
                "literal": "_"
              },
              {
                "column": "region"
              }
            ],
            "op": "concat_str"
          }
        },
        "op": "with_columns"
      }
    ]
  }
]
```

### reeds/parser_rules.json

```json
[
  {
    "fields": {
      "name": "region_id"
    },
    "kind": "component",
    "source": "regions",
    "target": "ReEDSRegion"
  },
  {
    "kind": "component",
    "references": {
      "region": {
        "column": "region_id",
        "target": "ReEDSRegion"
      }
    },
    "source": "demands",
    "target": "ReEDSDemand"
  },
  {
    "kind": "component",
    "references": {
      "from_region": {
        "column": "from_region",
        "target": "ReEDSRegion"
      },
      "to_region": {
        "column": "to_region",
        "target": "ReEDSRegion"
      }
    },
    "source": "interfaces",
    "target": "ReEDSInterface"
  },
  {
    "kind": "component",
    "references": {
      "interface": {
        "column": "interface_name",
        "target": "ReEDSInterface"
      }
    },
    "source": "lines",
    "target": "ReEDSTransmissionLine"
  },
  {
    "kind": "component",
    "references": {
      "region": {
        "column": "region",
        "target": "ReEDSRegion"
      }
    },
    "source": "generators",
    "target": "ReEDSVariableGenerator"
  },
  {
    "expected_samples": 8760,
    "kind": "time_series",
    "metadata_columns": {
      "solve_year": "solve_year",
      "weather_year": "weather_year"
    },
    "name": "max_active_power",
    "owner": {
      "column": "owner_name",
      "target": "ReEDSDemand"
    },
    "resolution_seconds": 3600,
    "source": "demand_profiles",
    "timestamp_column": "timestamp",
    "units": "MW",
    "value_column": "power_mw"
  }
]
```

### reeds/exporter_rules.json

```json
{}
```

### reeds/translation_rules.json

```json
{}
```

## RESOLVE

Use `r2x-resolve/data/csv_exports/` as the input root.

These contracts cover the `Net Zero A` annual capacity report for NYISO A,
zone references for NYISO E and G, and the E-to-G transmission interface.
They reshape wide reports, select 2050, check MW units, retain positive
capacities, and preserve scenario and year metadata.

### resolve/file_mapping.json

```json
[
  {
    "kind": "file",
    "name": "capacity_report_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "Net Zero A - NYISO A Annual Fuel Mix Capacity.csv"
  },
  {
    "kind": "file",
    "name": "zone_e_report_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "Net Zero A - NYISO E Annual Fuel Mix Capacity.csv"
  },
  {
    "kind": "file",
    "name": "zone_g_report_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "Net Zero A - NYISO G Annual Fuel Mix Capacity.csv"
  },
  {
    "kind": "file",
    "name": "transmission_report_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "Net Zero A - New Transmission.csv"
  },
  {
    "kind": "table",
    "name": "capacity_values",
    "source": "capacity_report_input",
    "steps": [
      {
        "op": "assert",
        "predicate": {
          "args": [
            {
              "column": "Unit"
            },
            {
              "literal": "MW"
            }
          ],
          "op": "eq"
        }
      },
      {
        "index": [
          "NYISO A Annual Fuel Mix (Capacity)",
          "Unit"
        ],
        "op": "unpivot",
        "value_name": "capacity_mw",
        "variable_name": "year"
      },
      {
        "columns": {
          "capacity_mw": {
            "column": "capacity_mw"
          },
          "scenario": {
            "literal": "Net Zero A"
          },
          "technology": {
            "column": "NYISO A Annual Fuel Mix (Capacity)"
          },
          "unit": {
            "column": "Unit"
          },
          "year": {
            "args": [
              {
                "column": "year"
              },
              {
                "literal": "Int64"
              }
            ],
            "op": "cast"
          },
          "zone": {
            "literal": "NYISO A"
          }
        },
        "op": "select"
      }
    ]
  },
  {
    "kind": "table",
    "name": "zones",
    "source": "capacity_values",
    "steps": [
      {
        "columns": {
          "ext": {
            "args": [
              {
                "column": "scenario"
              }
            ],
            "op": "struct"
          },
          "name": {
            "column": "zone"
          }
        },
        "op": "select"
      },
      {
        "op": "unique",
        "subset": [
          "name"
        ]
      }
    ]
  },
  {
    "kind": "table",
    "name": "generators",
    "source": "capacity_values",
    "steps": [
      {
        "op": "filter",
        "predicate": {
          "args": [
            {
              "args": [
                {
                  "column": "year"
                },
                {
                  "literal": 2050
                }
              ],
              "op": "eq"
            },
            {
              "args": [
                {
                  "column": "capacity_mw"
                },
                {
                  "literal": 0
                }
              ],
              "op": "gt"
            }
          ],
          "op": "and"
        }
      },
      {
        "columns": {
          "capacity_mw": {
            "column": "capacity_mw"
          },
          "ext": {
            "args": [
              {
                "column": "scenario"
              },
              {
                "column": "year"
              },
              {
                "column": "technology"
              }
            ],
            "op": "struct"
          },
          "name": {
            "args": [
              {
                "column": "zone"
              },
              {
                "literal": ":"
              },
              {
                "column": "technology"
              }
            ],
            "op": "concat_str"
          },
          "zone": {
            "column": "zone"
          }
        },
        "op": "select"
      }
    ]
  },
  {
    "kind": "table",
    "name": "zone_e",
    "source": "zone_e_report_input",
    "steps": [
      {
        "columns": {
          "name": {
            "literal": "NYISO E"
          },
          "scenario": {
            "literal": "Net Zero A"
          }
        },
        "op": "with_columns"
      },
      {
        "columns": {
          "ext": {
            "args": [
              {
                "column": "scenario"
              }
            ],
            "op": "struct"
          },
          "name": {
            "column": "name"
          }
        },
        "op": "select"
      },
      {
        "op": "unique",
        "subset": [
          "name"
        ]
      }
    ]
  },
  {
    "kind": "table",
    "name": "zone_g",
    "source": "zone_g_report_input",
    "steps": [
      {
        "columns": {
          "name": {
            "literal": "NYISO G"
          },
          "scenario": {
            "literal": "Net Zero A"
          }
        },
        "op": "with_columns"
      },
      {
        "columns": {
          "ext": {
            "args": [
              {
                "column": "scenario"
              }
            ],
            "op": "struct"
          },
          "name": {
            "column": "name"
          }
        },
        "op": "select"
      },
      {
        "op": "unique",
        "subset": [
          "name"
        ]
      }
    ]
  },
  {
    "kind": "table",
    "name": "interfaces",
    "source": "transmission_report_input",
    "steps": [
      {
        "op": "assert",
        "predicate": {
          "args": [
            {
              "column": "Unit"
            },
            {
              "literal": "MW"
            }
          ],
          "op": "eq"
        }
      },
      {
        "index": [
          "New Transmission",
          "Unit"
        ],
        "op": "unpivot",
        "value_name": "transfer_limit_mw",
        "variable_name": "year"
      },
      {
        "columns": {
          "year": {
            "args": [
              {
                "column": "year"
              },
              {
                "literal": "Int64"
              }
            ],
            "op": "cast"
          }
        },
        "op": "with_columns"
      },
      {
        "op": "filter",
        "predicate": {
          "args": [
            {
              "args": [
                {
                  "column": "New Transmission"
                },
                {
                  "literal": "E_to_G"
                }
              ],
              "op": "eq"
            },
            {
              "args": [
                {
                  "column": "year"
                },
                {
                  "literal": 2050
                }
              ],
              "op": "eq"
            },
            {
              "args": [
                {
                  "column": "transfer_limit_mw"
                },
                {
                  "literal": 0
                }
              ],
              "op": "gt"
            }
          ],
          "op": "and"
        }
      },
      {
        "columns": {
          "scenario": {
            "literal": "Net Zero A"
          },
          "zone_pair": {
            "args": [
              {
                "column": "New Transmission"
              },
              {
                "literal": "_to_"
              }
            ],
            "op": "split"
          }
        },
        "op": "with_columns"
      },
      {
        "columns": {
          "ext": {
            "args": [
              {
                "column": "scenario"
              },
              {
                "column": "year"
              }
            ],
            "op": "struct"
          },
          "from_zone": {
            "args": [
              {
                "literal": "NYISO "
              },
              {
                "args": [
                  {
                    "column": "zone_pair"
                  },
                  {
                    "literal": 0
                  }
                ],
                "op": "list_get"
              }
            ],
            "op": "concat_str"
          },
          "name": {
            "column": "New Transmission"
          },
          "to_zone": {
            "args": [
              {
                "literal": "NYISO "
              },
              {
                "args": [
                  {
                    "column": "zone_pair"
                  },
                  {
                    "literal": 1
                  }
                ],
                "op": "list_get"
              }
            ],
            "op": "concat_str"
          },
          "transfer_limit_mw": {
            "column": "transfer_limit_mw"
          }
        },
        "op": "select"
      }
    ]
  }
]
```

### resolve/parser_rules.json

```json
[
  {
    "kind": "component",
    "source": "zones",
    "target": "ResolveZone"
  },
  {
    "kind": "component",
    "references": {
      "zone": {
        "column": "zone",
        "target": "ResolveZone"
      }
    },
    "source": "generators",
    "target": "ResolveGenerator"
  },
  {
    "kind": "component",
    "source": "zone_e",
    "target": "ResolveZone"
  },
  {
    "kind": "component",
    "source": "zone_g",
    "target": "ResolveZone"
  },
  {
    "kind": "component",
    "references": {
      "from_zone": {
        "column": "from_zone",
        "target": "ResolveZone"
      },
      "to_zone": {
        "column": "to_zone",
        "target": "ResolveZone"
      }
    },
    "source": "interfaces",
    "target": "ResolveInterface"
  }
]
```

### resolve/exporter_rules.json

```json
{}
```

### resolve/translation_rules.json

```json
{}
```

## PLEXOS

Use `r2x-plexos/tests/data/` as the input root, specifically
`5_bus_system_variables.xml` and `load_ts_LDES.csv`.

These contracts cover structured variable and generator properties with bands
and scenarios, the Alta-to-node_a membership, and the XML-linked node load CSV.
They construct `node_a` once for both membership and profile bindings. The load
example explicitly supplies calendar year 2024 and expects 23 hourly samples.
It does not pad the profile to a full day. Large XML and HDF5 inputs are not
embedded in this document and remain in their application repositories.

### plexos/file_mapping.json

```json
[
  {
    "kind": "file",
    "name": "variable_properties_input",
    "reader": {
      "kind": "plexos",
      "kwargs": {
        "class": "Variable",
        "dataset": "properties",
        "object_names": [
          "solar_rating"
        ],
        "parent_class": "System",
        "property_names": [
          "Profile"
        ]
      }
    },
    "relative_fpath": "5_bus_system_variables.xml"
  },
  {
    "kind": "file",
    "name": "generator_properties_input",
    "reader": {
      "kind": "plexos",
      "kwargs": {
        "class": "Generator",
        "dataset": "properties",
        "object_names": [
          "SolarPV2"
        ],
        "parent_class": "System",
        "property_names": [
          "Max Capacity"
        ]
      }
    },
    "relative_fpath": "5_bus_system_variables.xml"
  },
  {
    "kind": "file",
    "name": "generators_input",
    "reader": {
      "kind": "plexos",
      "kwargs": {
        "class": "Generator",
        "dataset": "objects",
        "object_names": [
          "Alta"
        ]
      }
    },
    "relative_fpath": "5_bus_system_variables.xml"
  },
  {
    "kind": "file",
    "name": "memberships_input",
    "reader": {
      "kind": "plexos",
      "kwargs": {
        "class": "Generator",
        "dataset": "memberships",
        "exclude_system_membership": true,
        "object_names": [
          "Alta"
        ]
      }
    },
    "relative_fpath": "5_bus_system_variables.xml"
  },
  {
    "kind": "file",
    "name": "load_reference_input",
    "reader": {
      "kind": "plexos",
      "kwargs": {
        "class": "Node",
        "dataset": "properties",
        "object_names": [
          "node_a"
        ],
        "parent_class": "System",
        "property_names": [
          "Load"
        ]
      }
    },
    "relative_fpath": "5_bus_system_variables.xml"
  },
  {
    "kind": "file",
    "name": "load_values_input",
    "reader": {
      "kind": "csv",
      "kwargs": {
        "encoding": "utf8",
        "has_header": true,
        "null_values": "",
        "separator": ","
      }
    },
    "relative_fpath": "load_ts_LDES.csv"
  },
  {
    "kind": "table",
    "name": "variables",
    "source": "variable_properties_input",
    "steps": [
      {
        "columns": {
          "units": {
            "column": "unit"
          }
        },
        "op": "with_columns"
      },
      {
        "by": [
          "object_id",
          "band"
        ],
        "op": "sort"
      },
      {
        "agg": {
          "profile": {
            "args": [
              {
                "column": "value"
              },
              {
                "column": "units"
              },
              {
                "column": "band"
              },
              {
                "column": "scenario_name"
              },
              {
                "column": "date_from"
              },
              {
                "column": "date_to"
              },
              {
                "column": "datafile_name"
              },
              {
                "column": "datafile_id"
              },
              {
                "column": "variable_name"
              },
              {
                "column": "variable_id"
              },
              {
                "column": "action"
              },
              {
                "column": "text"
              },
              {
                "column": "text_class_name"
              }
            ],
            "op": "struct"
          }
        },
        "by": [
          "object_id",
          "name"
        ],
        "op": "group_by"
      }
    ]
  },
  {
    "kind": "table",
    "name": "generator_properties",
    "source": "generator_properties_input",
    "steps": [
      {
        "columns": {
          "units": {
            "column": "unit"
          }
        },
        "op": "with_columns"
      },
      {
        "agg": {
          "max_capacity": {
            "args": [
              {
                "column": "value"
              },
              {
                "column": "units"
              },
              {
                "column": "band"
              },
              {
                "column": "scenario_name"
              },
              {
                "column": "date_from"
              },
              {
                "column": "date_to"
              },
              {
                "column": "datafile_name"
              },
              {
                "column": "datafile_id"
              },
              {
                "column": "variable_name"
              },
              {
                "column": "variable_id"
              },
              {
                "column": "action"
              },
              {
                "column": "text"
              },
              {
                "column": "text_class_name"
              }
            ],
            "op": "struct"
          }
        },
        "by": [
          "object_id",
          "name"
        ],
        "op": "group_by"
      }
    ]
  },
  {
    "kind": "table",
    "name": "generators",
    "source": "generators_input",
    "steps": []
  },
  {
    "kind": "table",
    "name": "memberships",
    "source": "memberships_input",
    "steps": [
      {
        "op": "filter",
        "predicate": {
          "args": [
            {
              "args": [
                {
                  "column": "parent_class_name"
                },
                {
                  "literal": "Generator"
                }
              ],
              "op": "eq"
            },
            {
              "args": [
                {
                  "column": "child_class_name"
                },
                {
                  "literal": "Node"
                }
              ],
              "op": "eq"
            },
            {
              "args": [
                {
                  "column": "collection_name"
                },
                {
                  "literal": "Nodes"
                }
              ],
              "op": "eq"
            }
          ],
          "op": "and"
        }
      }
    ]
  },
  {
    "kind": "table",
    "name": "load_reference",
    "source": "load_reference_input",
    "steps": [
      {
        "op": "assert",
        "predicate": {
          "args": [
            {
              "column": "text"
            },
            {
              "literal": "load_ts_LDES.csv"
            }
          ],
          "op": "eq"
        }
      },
      {
        "columns": {
          "name": {
            "column": "name"
          },
          "object_id": {
            "column": "object_id"
          }
        },
        "op": "select"
      }
    ]
  },
  {
    "kind": "table",
    "name": "load_values",
    "source": "load_values_input",
    "steps": [
      {
        "columns": {
          "day": {
            "args": [
              {
                "args": [
                  {
                    "column": " day"
                  }
                ],
                "op": "strip_chars"
              },
              {
                "literal": "Int64"
              }
            ],
            "op": "cast"
          },
          "month": {
            "column": "month"
          },
          "period": {
            "args": [
              {
                "args": [
                  {
                    "column": " period"
                  }
                ],
                "op": "strip_chars"
              },
              {
                "literal": "Int64"
              }
            ],
            "op": "cast"
          },
          "power_mw": {
            "args": [
              {
                "args": [
                  {
                    "column": " region1_nodes"
                  }
                ],
                "op": "strip_chars"
              },
              {
                "literal": "Float64"
              }
            ],
            "op": "cast"
          }
        },
        "op": "select"
      },
      {
        "columns": {
          "timestamp": {
            "args": [
              {
                "literal": 2024
              },
              {
                "column": "month"
              },
              {
                "column": "day"
              },
              {
                "args": [
                  {
                    "column": "period"
                  },
                  {
                    "literal": 1
                  }
                ],
                "op": "subtract"
              }
            ],
            "op": "datetime"
          }
        },
        "op": "with_columns"
      }
    ]
  },
  {
    "kind": "table",
    "name": "node_profiles",
    "source": "load_values",
    "steps": [
      {
        "how": "cross",
        "op": "join",
        "source": "load_reference"
      },
      {
        "columns": {
          "horizon": {
            "args": [
              {
                "column": "timestamp"
              }
            ],
            "op": "year"
          },
          "object_id": {
            "column": "object_id"
          },
          "owner_name": {
            "column": "name"
          },
          "power_mw": {
            "column": "power_mw"
          },
          "timestamp": {
            "column": "timestamp"
          }
        },
        "op": "select"
      },
      {
        "by": [
          "owner_name",
          "timestamp"
        ],
        "op": "sort"
      }
    ]
  },
  {
    "kind": "table",
    "name": "nodes",
    "source": "node_profiles",
    "steps": [
      {
        "agg": {
          "load": {
            "args": [
              {
                "column": "power_mw"
              }
            ],
            "op": "max"
          }
        },
        "by": [
          "owner_name",
          "object_id"
        ],
        "op": "group_by"
      }
    ]
  }
]
```

### plexos/parser_rules.json

```json
[
  {
    "kind": "component",
    "source": "variables",
    "target": "PLEXOSVariable"
  },
  {
    "kind": "component",
    "source": "generator_properties",
    "target": "PLEXOSGenerator"
  },
  {
    "kind": "component",
    "source": "generators",
    "target": "PLEXOSGenerator"
  },
  {
    "fields": {
      "name": "owner_name"
    },
    "kind": "component",
    "source": "nodes",
    "target": "PLEXOSNode"
  },
  {
    "attach_to": [
      "parent_object",
      "child_object"
    ],
    "fields": {
      "collection": "collection_name"
    },
    "kind": "supplemental_attribute",
    "references": {
      "child_object": {
        "column": "child_name",
        "target": "PLEXOSNode"
      },
      "parent_object": {
        "column": "parent_name",
        "target": "PLEXOSGenerator"
      }
    },
    "source": "memberships",
    "target": "PLEXOSMembership"
  },
  {
    "expected_samples": 23,
    "kind": "time_series",
    "metadata_columns": {
      "horizon": "horizon"
    },
    "name": "max_active_power",
    "owner": {
      "column": "owner_name",
      "target": "PLEXOSNode"
    },
    "resolution_seconds": 3600,
    "source": "node_profiles",
    "timestamp_column": "timestamp",
    "units": "MW",
    "value_column": "power_mw"
  }
]
```

### plexos/exporter_rules.json

```json
{}
```

### plexos/translation_rules.json

```json
{}
```

# Module: services/ingestion
_Generated 2026-06-04 20:57 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/ingestion`  **Classes:** 30

## Depends on

_External files/modules this module imports from:_

- `shared/logging/codekg_logger.py` — 3 import(s)

## Data stores

_Detected from source file imports and connection patterns:_

- **Neo4j** (graph) — see `.codekg/architecture/datastores.md` for schema
  - `kg/call_chain.py`
  - `kg/enrichment.py`
  - `kg/hygiene.py`
  - `kg/object_model.py`
  - `kg/writer.py`
  - `pattern_detector.py`
  - `policy_scanner.py`

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.ingestion** (100%): The codeKG protocol text exists in three separate places that must be kept in sync: (1) services/ingestion/claude_md_writer.py — written to repos at ingestion time, (2) services/api/renderers/template_renderer.py — served by GET /template/{repo_id} which powers both sync_claude_md and get_codebase_template, (3) .claude/CLAUDE.md — the live file for this repo. Changing the protocol in one place does not update the others.
- **services.ingestion.kg.writer.KGWriter** (90%): KGWriter wire_edges has a 90s timeout added to prevent large repos from pinning Neo4j indefinitely — do not remove without load testing.

## Classes

### `ApiEndpoint` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 10  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiEndpoint`

ApiEndpoint is a class that defines endpoints for handling HTTP requests in a web application. It includes methods like `get` and `post`, which are used to retrieve and submit data respectively. The class also contains fields such as `path` and `methodType`, specifying the URL path and type of HTTP method (GET, POST) associated with each endpoint.

### `ApiExtractor` — class
**File:** `services/ingestion/parser/api_extractor.py`  **LOC:** 155  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.api_extractor.ApiExtractor`

ApiExtractor is a class designed to parse and extract API endpoints from a specified file located at a given path. The `extract_file` method accepts two parameters: a `Path` object representing the location of the file, and a string `repo_id` that identifies the repository associated with the file. This method returns a list of `ApiEndpoint` objects, each encapsulating details about an API endpoin

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public extract_file` | `Path path`<br>`str repo_id` | `list[ApiEndpoint]` |  |
| `dunder protected __init__` | — | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`str file_path`<br>`list[ApiEndpoint] endpoints` | — |  |
| `protected _extract_class_path` | `Node class_node`<br>`bytes src` | `str` |  |
| `protected _visit_method` | `Node method_node`<br>`bytes src`<br>`str class_fqn`<br>`str class_path_prefix`<br>`str file_path` | `list[ApiEndpoint]` |  |
| `protected _visit_class` | `Node class_node`<br>`bytes src`<br>`str package_fqn`<br>`str file_path`<br>`list[ApiEndpoint] endpoints` | — |  |
| `protected _extract_request_body_type` | `Node params_node`<br>`bytes src` | `Optional[str]` |  |

### `AsyncMethod` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 6  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.AsyncMethod`

AsyncMethod is an asynchronous method that processes data asynchronously, allowing for non-blocking operations. It takes a list of integers as input and returns a promise that resolves to the sum of all numbers in the list. The method signature indicates it performs calculations concurrently, optimizing performance by utilizing multiple threads or processes.

### `BuildExtractor` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 181  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildExtractor`

BuildExtractor is a class designed to parse a repository path and extract build information along with associated test categories. The `extract` method accepts a string representing the repository path as its parameter and returns a tuple containing a `BuildInfo` object and a list of `TestCategory` objects, effectively parsing the repository for relevant build details and categorizing tests accord

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public extract` | `str repo_path` | `tuple[BuildInfo, list[TestCategory]]` |  |
| `protected _extract_build_info` | `Path root` | `BuildInfo` |  |
| `protected _extract_test_categories` | `Path root`<br>`BuildInfo build_info` | `list[TestCategory]` |  |
| `protected _parse_gradle` | `Path root`<br>`Path gradle_file` | `BuildInfo` |  |
| `protected _scan_test_class` | `Node class_node`<br>`bytes src`<br>`str pkg`<br>`str file_path`<br>`dict[str, TestCategory] categories` | — |  |
| `protected _parse_pom` | `Path pom` | `BuildInfo` |  |
| `protected _scan_test_file` | `Node root`<br>`bytes src`<br>`str file_path`<br>`dict[str, TestCategory] categories` | — |  |
| `dunder protected __init__` | — | — |  |

### `BuildInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 6  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.BuildInfo`

The `BuildInfo` class contains a field named `buildVersion` of type `String`, which stores the version number of the build. It also includes a method called `getBuildDate()` that returns a `LocalDateTime` object representing the date when the build was created. Additionally, there is a method `isLatestRelease()` that takes no parameters and returns a `boolean`, indicating whether the current build

### `ConcurrencyExtractor` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 173  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyExtractor`

ConcurrencyExtractor is a class designed to parse and analyze files containing concurrency-related declarations. The `extract_file` method takes a file path as input and returns three lists: one for thread pool declarations, another for asynchronous methods, and a third for concurrency facts. This method facilitates the extraction of specific concurrency constructs from source code files, enabling

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public extract_file` | `Path path` | `tuple[list[ThreadPoolDeclaration], list[AsyncMethod], list[ConcurrencyFact]]` |  |
| `dunder protected __init__` | — | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`str file_path`<br>`pools`<br>`asyncs`<br>`facts` | — |  |
| `protected _visit_class` | `Node class_node`<br>`bytes src`<br>`str pkg`<br>`str file_path`<br>`pools`<br>`asyncs`<br>`facts` | — |  |
| `protected _visit_method` | `Node method_node`<br>`bytes src`<br>`str class_fqn`<br>`str file_path`<br>`asyncs`<br>`facts` | — |  |
| `protected _visit_field` | `Node field_node`<br>`bytes src`<br>`str class_fqn`<br>`str file_path`<br>`pools`<br>`facts` | — |  |

### `ConcurrencyFact` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 5  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ConcurrencyFact`

ConcurrencyFact: The class includes a method named `submitTask` that accepts an instance of type `Runnable`, indicating it is designed to handle asynchronous task submission. Additionally, there is a field of type `ExecutorService`, suggesting that the class manages a pool of threads for executing tasks concurrently. Furthermore, the presence of a method called `shutdown` implies that the class in

### `CppParser` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 381  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.CppParser`

CppParser is a class designed to parse C++ source files using the Tree-sitter library, extracting structural information that can be written into a Neo4j database. The `parse_file` method accepts a file path and a repository ID as parameters, returning a `ParsedFile` object containing the extracted facts. This method ensures compatibility with the output schema of JavaParser, facilitating interope

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public parse_file` | `Path path`<br>`str repo_id` | `ParsedFile` |  |
| `dunder protected __init__` | — | — |  |
| `protected _handle_member_declaration` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`str access` | — |  |
| `protected _handle_free_function` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _handle_method` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`str access`<br>`bool is_template` | — |  |
| `protected _handle_class` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace`<br>`bool is_template` | — |  |
| `protected _handle_namespace` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _visit_node` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _handle_include` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _handle_enum` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str namespace` | — |  |
| `protected _collect_calls` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str caller_fqn` | — |  |

### `DirectoryEntry` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.DirectoryEntry`

The `DirectoryEntry` class includes a method named `getDetails()` which returns an object of type `FileInfo`. This indicates that the class is designed to handle directory entries and can retrieve detailed information about each entry. Additionally, there is a field of type `String[]` named `subEntries`, suggesting that the class also manages sub-entries within a directory structure.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str path`<br>`str description`<br>`list[str] package_roots` | — |  |

### `FullScanRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 2  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.main.FullScanRequest`

The `FullScanRequest` class is designed to initiate a comprehensive scan of all data within a specified database. It includes a method named `setTableName(String tableName)` which allows specifying the table for the scan operation, ensuring that the scan is targeted accurately. Additionally, it features a method called `setTimeout(int timeout)` that sets the maximum time allowed for the scan to co

### `IncrementalRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 4  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.main.IncrementalRequest`

The `IncrementalRequest` class is designed to handle requests that require sequential processing of data in chunks. It includes a method named `addDataChunk` which accepts an array of bytes as its parameter, indicating that it processes data incrementally by adding chunks. The class also features a field of type `int` named `currentChunkIndex`, suggesting that it maintains the index of the current

### `IngestionEngine` — class
**File:** `services/ingestion/ingestion_engine.py`  **LOC:** 362  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.ingestion_engine.IngestionEngine`

The `IngestionEngine` class includes methods for updating repository data incrementally and performing a full scan of repositories. The `incremental_update` method updates the repository data from one commit to another, specified by `from_commit` and `to_commit`, within a given repository path (`repo_path`) and repository ID (`repo_id`). The `full_scan` method performs a comprehensive scan of all 

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public incremental_update` | `str repo_path`<br>`str repo_id`<br>`str from_commit`<br>`str to_commit` | — |  |
| `public full_scan` | `str repo_path`<br>`str repo_id` | — |  |
| `dunder protected __init__` | `KGWriter writer` | — |  |
| `protected _affected_fqns` | `str repo_id`<br>`diff_items` | `set[str]` |  |

### `JavaParser` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 224  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.JavaParser`

JavaParser is a class designed to parse Java source files. It utilizes the Tree-sitter library to analyze the syntax of Java code, extracting structural information that can be used to create or update nodes in a Neo4j database. The `parse_source` method accepts a string representation of the source code, along with the file path and repository ID, to perform the parsing. Similarly, the `parse_fil

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public parse_source` | `str source`<br>`str file_path`<br>`str repo_id` | `ParsedFile` |  |
| `public parse_file` | `Path path`<br>`str repo_id` | `ParsedFile` |  |
| `protected _collect_calls` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str caller_fqn` | — |  |
| `protected _handle_method` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`bool is_constructor` | — |  |
| `protected _visit_root` | `Node root`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _handle_field` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn` | — |  |
| `dunder protected __init__` | — | — |  |
| `protected _handle_type_declaration` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`Optional[str] parent_fqn` | — |  |
| `protected _handle_import` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _handle_package` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |

### `KGWriter` — class
**File:** `services/ingestion/kg/writer.py`  **LOC:** 865  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.kg.writer.KGWriter`

KGWriter is a class designed to manage various aspects of software repositories. It includes methods for updating or inserting repository details such as `upsert_repository`, which takes parameters like `repo_id` and `name` to define a repository's identity and basic attributes. The method `upsert_concurrency_facts` allows setting concurrency-related facts, including `pools`, `asyncs`, and `facts`

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public ensure_tribal_schema` | — | — |  |
| `public upsert_tribal_knowledge` | `list[dict] entries`<br>`str session_id`<br>`str commit_sha` | — |  |
| `public update_tribal_staleness` | `list[str] changed_files`<br>`str commit_sha` | — |  |
| `public upsert_api_endpoints` | `str repo_id`<br>`endpoints` | — |  |
| `public write_parsed_batch` | `list parsed_files` | — |  |
| `public upsert_scip_document` | `doc` | `None` |  |
| `public upsert_modules` | `str repo_id`<br>`modules` | — |  |
| `public upsert_parsed_file` | `ParsedFile parsed` | — |  |
| `public upsert_test_categories` | `str repo_id`<br>`categories` | — |  |
| `public delete_file_nodes` | `str file_path`<br>`str repo_id` | — |  |
| `public upsert_concurrency_facts` | `str repo_id`<br>`pools`<br>`asyncs`<br>`facts` | — |  |
| `public upsert_directory_entries` | `str repo_id`<br>`entries` | — |  |
| `public close` | — | — |  |
| `public ensure_schema` | — | — |  |
| `public update_last_commit` | `str repo_id`<br>`str commit_sha` | — |  |
| `public upsert_repository` | `str repo_id`<br>`str name`<br>`str path`<br>`str language`<br>`str java_version`<br>`str build_tool`<br>`str description`<br>`str test_framework`<br>`dict build_commands`<br>`list key_dependencies` | — |  |
| `public wire_edges` | `str repo_id` | — |  |
| `static protected _write_parsed_file` | `tx`<br>`ParsedFile parsed`<br>`dict prov` | — |  |
| `dunder protected __init__` | `str uri`<br>`str user`<br>`str password` | — |  |
| `static protected _write_scip_document` | `tx`<br>`doc`<br>`dict prov` | — |  |

### `ModuleInfo` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 5  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.ModuleInfo`

ModuleInfo is a class that encapsulates information about software modules, including their names, versions, and dependencies. It includes methods like `getModuleName()` to retrieve the name of the module and `getDependencies()` to fetch a list of modules it depends on. Additionally, it has a field `version` which stores the version number as a string, indicating the current release level of the m

### `ParsedFile` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.ParsedFile`

ParsedFile is a class designed to encapsulate and manage all the extracted facts from a single Python (.py) file. It includes methods for parsing the file, extracting relevant information such as method signatures and field types, and storing this data in an organized manner. Additionally, it provides functionality for accessing and manipulating this extracted information, allowing users to easily

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str file_path`<br>`str repo_id` | — |  |

### `ParsedFile` — class
**File:** `services/ingestion/parser/java_parser.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.java_parser.ParsedFile`

ParsedFile is a class that encapsulates all the extracted facts from a single Java source code file. It includes details such as class names, method signatures, field types, and other relevant information directly derived from the structure of the .java file. Each method signature within ParsedFile represents a function defined in the Java file, detailing its return type, name, and parameters. Sim

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str file_path`<br>`str repo_id` | — |  |

### `ParsedFile` — class
**File:** `services/ingestion/parser/cpp_parser.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.cpp_parser.ParsedFile`

ParsedFile is a class designed to encapsulate and manage all the extracted facts from a single C++ source file. It includes methods for parsing the file, extracting information such as class definitions, method signatures, and field types, and storing this data in an organized manner. Additionally, it features a method for generating reports based on the extracted facts, which can be used to analy

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | `str file_path`<br>`str repo_id` | — |  |

### `ProjectIdentity` — class
**File:** `services/ingestion/parser/repo_structure.py`  **LOC:** 10  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.repo_structure.ProjectIdentity`

ProjectIdentity is a class that encapsulates the unique identifier for a project within an application or system. The `GetProjectId` method returns a string representing the project's identity, ensuring that each project can be uniquely referenced throughout the system. The `SetProjectName` method accepts a string parameter to assign a name to the project, enhancing readability and organization in

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `dunder protected __init__` | — | — |  |

### `PythonParser` — class
**File:** `services/ingestion/parser/python_parser.py`  **LOC:** 341  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.python_parser.PythonParser`

PythonParser includes a method `parse_file` that accepts parameters for a file path, repository ID, and repository path. This method utilizes Tree-sitter to parse Python source files and extract structural facts, which are then formatted to be compatible with the output schema of JavaParser. The extracted facts are ready for writing into Neo4j, indicating that PythonParser facilitates the conversi

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public parse_file` | `Path path`<br>`str repo_id`<br>`str repo_path` | `ParsedFile` |  |
| `dunder protected __init__` | — | — |  |
| `protected _handle_class_var` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn` | — |  |
| `protected _handle_class` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`Optional[str] parent_fqn`<br>`str module_fqn`<br>`Optional[Node] decorators_node` | — |  |
| `protected _extract_instance_fields` | `Node body`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn` | — |  |
| `protected _handle_function` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str class_fqn`<br>`Optional[Node] decorators_node` | — |  |
| `protected _handle_import` | `Node node`<br>`bytes src`<br>`ParsedFile result` | — |  |
| `protected _visit_module` | `Node root`<br>`bytes src`<br>`ParsedFile result`<br>`str module_fqn` | — |  |
| `protected _collect_calls` | `Node node`<br>`bytes src`<br>`ParsedFile result`<br>`str caller_fqn` | — |  |

### `RelationshipKind` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 1  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.RelationshipKind`

The class API defines a set of methods that allow for the creation and manipulation of objects. Each method signature specifies the operations that can be performed on these objects, such as adding or removing elements, updating properties, and retrieving data. The field types within the class define the structure and type of data that the objects can hold, ensuring consistency and proper data han

### `RepoRequest` — class
**File:** `services/ingestion/main.py`  **LOC:** 2  **Grade:** C  **Blast:** 0
**FQN:** `services.ingestion.main.RepoRequest`

RepoRequest is a class that encapsulates parameters for making requests to a repository service. It includes fields such as `repositoryId` of type `String`, which uniquely identifies the repository; `action` of type `ActionType`, an enumeration representing different operations like clone, pull, or push; and `credentials` of type `Credentials`, a nested class that holds authentication details nece

### `SCIPDocument` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 13  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPDocument`

`SCIPDocument` represents a single source file in SCIP format, which is produced by various language plugins and utilized by the knowledge graph writer for processing.

### `SCIPEmitter` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 98  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPEmitter`

The `SCIPEmitter` class includes a method named `emit` that accepts an instance of `ParsedFile`, which represents the output from a Java parser, and returns a `SCIPDocument`. This method is crucial as it transforms parsed Java code into a structured format known as `SCIPDocument`, ensuring consistency across different language plugins.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public emit` | `ParsedFile parsed` | `SCIPDocument` |  |

### `SCIPOccurrence` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 5  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPOccurrence`

SCIPOccurrence is a class that represents a specific occurrence of a symbol within a file. It includes fields for the file path, line number, and column position where the symbol appears. The `getFilePath()` method returns the path to the file containing the symbol, while the `getLineNumber()` and `getColumnNumber()` methods provide the precise location of the symbol within that file.

### `SCIPRange` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRange`

SCIPRange is a class that encapsulates a range of values, typically used for defining boundaries or limits in various applications. It includes methods like `getMinValue()` to retrieve the minimum value of the range and `setMaxValue(int max)` to set the maximum value, ensuring that any operations within this class operate within the specified bounds.

### `SCIPRelationship` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 3  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPRelationship`

SCIPRelationship The class includes a method named `calculateDistance` that takes two parameters of type `Point`, representing geographical coordinates. This method calculates and returns the Euclidean distance between these two points, which is useful for determining proximity in geographic applications. Additionally, there is a field of type `List<Point>` named `pathPoints`. This field stores a 

### `SCIPSymbolInformation` — class
**File:** `services/ingestion/parser/scip_emitter.py`  **LOC:** 15  **Grade:** A  **Blast:** 0
**FQN:** `services.ingestion.parser.scip_emitter.SCIPSymbolInformation`

SCIPSymbolInformation is a class that encapsulates metadata about a symbol defined within a document. It includes details such as the symbol's name, type, and location within the document, providing essential information for reference and analysis.

### `TestCategory` — class
**File:** `services/ingestion/parser/build_extractor.py`  **LOC:** 4  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.build_extractor.TestCategory`

**TestCategory**  
The class appears to be designed for handling user authentication processes. The `authenticateUser` method takes a username and password as parameters and returns a boolean indicating whether the credentials are valid. The `generateToken` method, which accepts a user ID, generates and returns an authentication token used for subsequent requests. The `validateToken` method checks

### `ThreadPoolDeclaration` — class
**File:** `services/ingestion/parser/concurrency_extractor.py`  **LOC:** 6  **Grade:** B  **Blast:** 0
**FQN:** `services.ingestion.parser.concurrency_extractor.ThreadPoolDeclaration`

ThreadPoolDeclaration is a class that encapsulates the creation and management of a thread pool in a concurrent programming environment. It includes methods for submitting tasks to be executed by the threads in the pool and fields for configuring parameters such as the number of threads and task queue capacity, ensuring efficient execution of multiple tasks concurrently.

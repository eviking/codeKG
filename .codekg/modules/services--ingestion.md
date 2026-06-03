# Module: services/ingestion
_Generated 2026-06-03 19:47 UTC_

**Path:** `/host-home/Documents/projects/codeKG/services/ingestion`  
**Classes:** 30

## All classes

_Full list sorted by blast radius (impact if changed). Grade A=clean, F=needs attention._

| Class | Kind | Grade | Blast | Methods | Description |
|---|---|---|---|---|---|
| `ApiEndpoint` | class | B | 0 | 0 | ApiEndpoint is a class that defines endpoints for handling HTTP requests in a web application. It includes methods like  |
| `ApiExtractor` | class | B | 0 | 7 | ApiExtractor is a class designed to parse and extract API endpoints from a specified file located at a given path. The ` |
| `AsyncMethod` | class | B | 0 | 0 | AsyncMethod is an asynchronous method that processes data asynchronously, allowing for non-blocking operations. It takes |
| `BuildExtractor` | class | B | 0 | 8 | BuildExtractor is a class designed to parse a repository path and extract build information along with associated test c |
| `BuildInfo` | class | B | 0 | 0 | The `BuildInfo` class contains a field named `buildVersion` of type `String`, which stores the version number of the bui |
| `ConcurrencyExtractor` | class | B | 0 | 6 | ConcurrencyExtractor is a class designed to parse and analyze files containing concurrency-related declarations. The `ex |
| `ConcurrencyFact` | class | B | 0 | 0 | ConcurrencyFact: The class includes a method named `submitTask` that accepts an instance of type `Runnable`, indicating  |
| `CppParser` | class | A | 0 | 12 | CppParser is a class designed to parse C++ source files using the Tree-sitter library, extracting structural information |
| `DirectoryEntry` | class | B | 0 | 1 | The `DirectoryEntry` class includes a method named `getDetails()` which returns an object of type `FileInfo`. This indic |
| `FullScanRequest` | class | C | 0 | 0 | The `FullScanRequest` class is designed to initiate a comprehensive scan of all data within a specified database. It inc |
| `IncrementalRequest` | class | C | 0 | 0 | The `IncrementalRequest` class is designed to handle requests that require sequential processing of data in chunks. It i |
| `IngestionEngine` | class | B | 0 | 4 | The `IngestionEngine` class includes methods for updating repository data incrementally and performing a full scan of re |
| `JavaParser` | class | A | 0 | 10 | JavaParser is a class designed to parse Java source files. It utilizes the Tree-sitter library to analyze the syntax of  |
| `KGWriter` | class | C | 0 | 20 | KGWriter is a class designed to manage various aspects of software repositories. It includes methods for updating or ins |
| `ModuleInfo` | class | B | 0 | 0 | ModuleInfo is a class that encapsulates information about software modules, including their names, versions, and depende |
| `ParsedFile` | class | A | 0 | 1 | ParsedFile is a class designed to encapsulate and manage all the extracted facts from a single Python (.py) file. It inc |
| `ParsedFile` | class | A | 0 | 1 | ParsedFile is a class that encapsulates all the extracted facts from a single Java source code file. It includes details |
| `ParsedFile` | class | A | 0 | 1 | ParsedFile is a class designed to encapsulate and manage all the extracted facts from a single C++ source file. It inclu |
| `ProjectIdentity` | class | B | 0 | 1 | ProjectIdentity is a class that encapsulates the unique identifier for a project within an application or system. The `G |
| `PythonParser` | class | A | 0 | 9 | PythonParser includes a method `parse_file` that accepts parameters for a file path, repository ID, and repository path. |
| `RelationshipKind` | class | B | 0 | 0 | The class API defines a set of methods that allow for the creation and manipulation of objects. Each method signature sp |
| `RepoRequest` | class | C | 0 | 0 | RepoRequest is a class that encapsulates parameters for making requests to a repository service. It includes fields such |
| `SCIPDocument` | class | A | 0 | 0 | `SCIPDocument` represents a single source file in SCIP format, which is produced by various language plugins and utilize |
| `SCIPEmitter` | class | A | 0 | 1 | The `SCIPEmitter` class includes a method named `emit` that accepts an instance of `ParsedFile`, which represents the ou |
| `SCIPOccurrence` | class | A | 0 | 0 | SCIPOccurrence is a class that represents a specific occurrence of a symbol within a file. It includes fields for the fi |
| `SCIPRange` | class | B | 0 | 0 | SCIPRange is a class that encapsulates a range of values, typically used for defining boundaries or limits in various ap |
| `SCIPRelationship` | class | B | 0 | 0 | SCIPRelationship The class includes a method named `calculateDistance` that takes two parameters of type `Point`, repres |
| `SCIPSymbolInformation` | class | A | 0 | 0 | SCIPSymbolInformation is a class that encapsulates metadata about a symbol defined within a document. It includes detail |
| `TestCategory` | class | B | 0 | 0 | **TestCategory**   The class appears to be designed for handling user authentication processes. The `authenticateUser` m |
| `ThreadPoolDeclaration` | class | B | 0 | 0 | ThreadPoolDeclaration is a class that encapsulates the creation and management of a thread pool in a concurrent programm |

## Dependency map

**This module imports from:**
- `shared/logging/codekg_logger.py` (3 imports)

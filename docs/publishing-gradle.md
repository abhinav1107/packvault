# Publishing with Gradle

Repository URL pattern:

```
https://<host>/<repositoryName>/
```

Example `build.gradle.kts`:

```kotlin
publishing {
    repositories {
        maven {
            name = "packvaultReleases"
            url = uri("https://packvault.example/releases")
            credentials {
                username = "ci-publisher"
                password = findProperty("packvaultToken") as String?
                    ?: System.getenv("PACKVAULT_TOKEN")
            }
        }
    }
}
```

Use a token with `write` permission on the target repository. See [configuration.md](configuration.md).

# Publishing with Gradle

PackVault exposes Maven-compatible repository URLs.

Repository URL pattern:

```text
https://<host>/<repositoryName>
```

Examples:

```text
https://packvault.example/releases
https://packvault.example/snapshots
```

For local Docker Compose:

```text
http://localhost:8080/releases
http://localhost:8080/snapshots
```

## Authentication

Gradle uses HTTP Basic authentication.

| Field    | Value                |
|----------|----------------------|
| Username | PackVault token name |
| Password | raw token secret     |

Example:

```text
username = ci-publisher
password = raw token value
```

PackVault config stores only the token hash. Gradle must use the raw token.

## Kotlin DSL publishing example

```kotlin
plugins {
    `java-library`
    `maven-publish`
}

group = "com.acme"
version = "1.0.0"

publishing {
    publications {
        create<MavenPublication>("mavenJava") {
            from(components["java"])
        }
    }

    repositories {
        maven {
            name = "packvaultReleases"
            url = uri("https://packvault.example/releases")

            credentials {
                username = "ci-publisher"
                password = findProperty("packvaultToken") as String?
                    ?: System.getenv("PACKVAULT_TOKEN")
            }
        }
    }
}
```

Publish:

```bash
PACKVAULT_TOKEN='<raw-token>' ./gradlew publish
```

## Snapshot publishing

For snapshots, use the snapshots repository:

```kotlin
publishing {
    repositories {
        maven {
            name = "packvaultSnapshots"
            url = uri("https://packvault.example/snapshots")

            credentials {
                username = "ci-publisher"
                password = findProperty("packvaultToken") as String?
                    ?: System.getenv("PACKVAULT_TOKEN")
            }
        }
    }
}
```

Use a snapshot version:

```kotlin
version = "1.0.0-SNAPSHOT"
```

## Local Docker Compose example

```kotlin
publishing {
    repositories {
        maven {
            name = "packvaultLocal"
            url = uri("http://localhost:8080/releases")

            credentials {
                username = "ci-publisher"
                password = System.getenv("PACKVAULT_TOKEN")
            }
        }
    }
}
```

Run:

```bash
PACKVAULT_TOKEN='<raw-token>' ./gradlew publish
```

## Consuming dependencies from PackVault

```kotlin
repositories {
    maven {
        url = uri("https://packvault.example/releases")

        credentials {
            username = "app-reader"
            password = findProperty("packvaultToken") as String?
                ?: System.getenv("PACKVAULT_TOKEN")
        }
    }

    mavenCentral()
}
```

Then declare dependencies normally:

```kotlin
dependencies {
    implementation("com.acme:demo:1.0.0")
}
```

## Repository permissions

Use a token with the correct permission on the target repository.

| Action           | Required permission |
|------------------|---------------------|
| publish/upload   | `write`             |
| resolve/download | `read`              |

A reader token cannot publish. A publisher token should usually have both `read` and `write` for the target repository.

## Release vs snapshot behavior

Default PackVault policy:

| Repository  | Overwrite behavior                        |
|-------------|-------------------------------------------|
| `releases`  | overwrite blocked; returns `409 Conflict` |
| `snapshots` | overwrite allowed                         |

This means release versions should be unique. Snapshot versions may be republished.

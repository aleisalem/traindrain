MANDATORY: Ask if you do not have enough context

# Project Overview

This project is a web application developed mainly using AI agents and LLMs, such as Claude Code or Ollama models.

The directory where the application code is kept is @src. For web applications, keep the frontend stored under @src/frontend and a backend stored under @src/backend.

Regardless of the programming language or target platforms, the developed applications are expected to process internal, sensitive, and potentially personal data. Prioritize security and privacy by adopting security best practices.

The applications should be built to be reliable, scalable, and extensible. We are expecting to receive feature requests to implement or modify existing features.

## App Description

This is a web-app meant to be a platform for elearning and awareness that can be customized for different topics, such as workplace safety, information security, programming, etc.

The following are the main functionalities of the app:
1. Users with the necessary permissions can create learning campaigns that are basically a collection of learning modules targeting specific groups of users.
2. Users with necessary permissions can create, edit, delete, and import learning modules, assign them to specific users and groups of users, add them and remove them from campaigns.
3. Learning modules can be generated using AI by describing the content of the module in a chatbot. The chat continues to enhance and regenerated the content, until the user saves the module.
4. Training modules can be configured to be graded and require passing a quiz at the end of the material.
5. Users can also directly chat with an AI bot about various topics. The platform is an awareness platform not just a classical training platform. Whatever means necessary to educate users about a specific topic are legitimate.
6. The system can be configured to connect to RSS feeds and different news outlets to retrieve recent news about a field, say information security, and generate and display "nuggets" of information via LLMs configured by the admin users.
7. The system look and feel are configurable to fit the colors and motifs of different organizations and is configurable by users with the necessary permissions.
8. The permissions model works using roles: Different actions within the system are accessible as "read-only", "read and write" or "none". Users with the role Administrator have "read and write" access to all functionalities and actions and can manage roles and members of those roles as individual users or user groups.
9. Users can be imported into the system using HRIS systems, Google Workspace, or by invitation. Initially, we will focus on invitations to indviduals before adding more integrations.
10. Progress of trainings and trainees can be viewed via dashboards by users with the necessary permissions. Dashboards can also be created using AI prompts.

## Documentation

The developed application is developed in a collaborative manner. Documentation is IMPORTANT.

Always update the @README.md file to include the following:

1. A BRIEF and SHORT description of the currently-supported features.
2. The structure of the project and a BRIEF description of each component.
3. Instructions on how to run the project locally.
4. Instructions on how to run the tests in the project.
5. Instructions on how to deploy the project to AWS.

Only store summaries of developed features in Markdown format under the @docs/ directory with a BRIEF description of was has changed.

## Process

Before implementing a feature, thoroughly plan it and interact with the user to gather as much information as possible about its technical details. 

Adopt the following process, unless otherwise instructed by the user:
1. Ask the user first whether they want to use @.claude/skills/wayfinder if they are not sure how to go about implementing a feature or the @.claude/skills/grilling skill to gather as much information as possible about the feature(s).
2. Once done run the @.claude/skills/to-spec to create specs for your feature.
3. Use @.claude/skills/to-tickets to break down the specs into digestable tickets to be implemented on at a time.
4. Use @.claude/skills/implement to implement the generated tickets according to the instructions in @AGENTS.md
5. Perform a code review using @.claude/skills/code-review

## Design

In general, KEEP THE DESIGN SIMPLE.

When deciding upon technologies to use to implement a feature, KEEP IN MIND that the solution will be deployed to AWS.

Whenever possible, design a feature to use a localized, simulated version of an AWS service using Localstack. Use the instructions here to setup Localstack CLI on the user machine and ask for the personal auth token or retrieve it from the @.env file.

### User Interface

For this partivular project, make the system UI design interactive, modern, and responsive. This system is trying to make elearning fun not boring.

ALWAYS offer a German and an English translations of the web application and its content.

ALWAYS offer a dark theme, a light theme, and a color-blind-friendly theme of the web application.

### Programming Languages

Unless otherwise instructed by the user, use the following programming languages:
1. For web applications with front and backend, use Python as the main programming language for the backend and Typescript for the frontend.
2. For mobile applications, prefer the usage of Flutter and Dart and Golang as the programming language for the backend/API.

The communication between the frontend and the backend of the web app should be accomplished via API endpoints that can also be used independent of the frontend via scoped API tokens generated by users with the necessary permissions.

Limit the functionalities of endpoints to atomic tasks to avoid inflated logic. A good example would be an endpoint that focuses on the CRUD operations of one type of objects.

### Infrastructure

Priortize hosting the infrastructure on EU-based data centers, such as on AWS in the "eu-central-1" region. 

Use terraform scripts to declare the services that need to be deployed for the web app to work and save the scripts under @.deploy in a directory with a name corresponding to the environment on which the services will be deployed, such as `dev`, `staging`, and `production`.

Use the following resources as references for best practices in how to create and destroy AWS resources using terraform:
1. https://github.com/aws-samples/aws-terraform-best-practices
2. https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/security.html
3. https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/backend.html
4. https://docs.aws.amazon.com/prescriptive-guidance/latest/terraform-aws-provider-best-practices/structure.html

## Security

ALWAYS observe the following instructions to ensure a minimal level of security:

1. NEVER hardcode secrets, such as credentials, passwords, API tokens, etc., in the codebase. Always retrieve secrets dynamically from the runtime environment either injected into environment variables or retrieved from a secret management platform.
2. ALWAYS use the implicit deny principle. A user will never have access to features/pages/features until they are explicitly defined by an admin user.
3. ALWAYS ensure that users need to be authenticated. NEVER implement anonymous access. If the authentication middleware fails, block access entirely to the application.
4. Observe security best practices to avoid the OWASP Top 10 vulnerabilities, such as injection, IDOR, SSRF, CSRF, et cetera.
5. ALWAYS use cryptographic-safe algorithms to generate secrets, such as passwords and API tokens.

## Testing & Deployment

For any feature you generate, ALWAYS generate unit and integration test cases.

Make sure that the entire solution can be run locally via, for example, `docker-compose`.

For every feature, also update the terraform scripts with the services and the configurations that need to be added or updated for the new feature to run.


# Overview

This is **NOT** a typical `SECURITY.md` file instructing users on how to report vulnerabilities.

In this file, you can list security-related requirements and assumptions in your application to give more context during design, implementation, and security reviews.

For example, you can have the following sections:

## Well-Known Issues

### Running as Root
We run our services using the `root` user and privileges because that is the only way to deliver our services.

We complement this escalated privileges with rigorous, immutable real-time monitoring of user/services activities.

## Security of Personal Data

This application processes the following type of personal data:
1. First and lastnames,
2. Physical address,
3. Health conditions, 
4. etc.

This data MUST be stored on EU-based servers and anonymized at all times.


## You get the gist ... 
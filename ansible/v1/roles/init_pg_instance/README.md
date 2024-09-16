Role Name
=========

Sets up a simple one-node Postgres instance from the PGDG repos on Ubuntu

Requirements
------------



Role Variables
--------------

Defaults are in `defaults/main.yml`. Following vars should normally be overridden in calling playbooks:

- pg.major_ver
- pg.admin_user
- pg.admin_is_superuser
- pg.admin_password

Dependencies
------------

- community.postgresql

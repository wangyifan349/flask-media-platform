# Flask Media Platform

[English](README.md) | [简体中文](README.zh.md)

## Project Overview

Flask Media Platform is a lightweight web application for organizing and sharing personal video and image collections. After registering and signing in, users can create albums, upload multiple media files, and choose whether each album is public or hidden.

The project focuses on account management, album management, media storage, large-file uploading, and user search. It intentionally does not include comments, bullet comments, likes, favorites, or complex social features. It can be used as a personal video site, a portfolio, an internal media library, or a practical Flask project.

The interface is responsive and works on phones, tablets, and desktop computers. Bootstrap CSS, project CSS, Bootstrap JavaScript, and application JavaScript are rendered inline through Jinja templates, so the application does not depend on its own external CSS or JavaScript files. Custom literal colors are configured with a blue channel value of `0`.

## Main Features

### User Accounts

- User registration
- Sign in and sign out
- Password changes
- Password hashing
- Login-state validation
- CSRF protection

### Album Management

- Create albums
- Rename albums
- Delete albums
- Set albums to public or hidden
- Manage albums through dropdown menus
- Open the album action menu with right-click on desktop
- Restrict hidden albums to their owners
- Delete database records and local media files together

Albums do not require descriptions. Users only enter an album name and choose its visibility.

### Video and Image Uploads

- Multiple file selection
- Drag-and-drop uploading
- Folder selection
- Automatic video filtering during folder upload
- No title or description fields
- Original file names used as display names
- AJAX uploads
- Chunked large-file uploads
- 8 MB default chunk size
- 8 GB default maximum file size
- Automatic retry for failed chunks
- Upload resumption when the same file is selected again
- Independent progress and status for each file
- A failed file does not stop the remaining queue
- AJAX media deletion

Duplicate names inside the same album are handled without overwriting existing files:

```text
video.mp4
video (2).mp4
video (3).mp4
```

### User Search and Public Profiles

- Search by username
- Search by display name
- View public user profiles
- View public albums
- Hidden albums are excluded from public pages and search results

### Responsive Interface

- Phone, tablet, and desktop support
- Collapsible mobile navigation
- Responsive forms, buttons, and upload queues
- Album grids that adapt to screen width
- Responsive video, image, and cover sizing
- Larger touch targets on mobile devices
- Functional interface without unnecessary marketing sections

## Technology

| Layer | Technology |
| --- | --- |
| Backend | Python, Flask |
| Database | SQLite3 |
| Templates | Jinja2 |
| Interface | HTML5, Bootstrap |
| Frontend logic | Vanilla JavaScript, AJAX |
| Upload system | Multi-select, drag and drop, folder selection, chunked upload |
| Password handling | Werkzeug Password Hashing |

## Main Database Tables

### `users`

Stores user account data:

- User ID
- Username
- Display name
- Password hash
- Registration time

### `albums`

Stores album data:

- Album ID
- Owner user ID
- Album name
- Hidden status
- Creation time
- Update time

### `media`

Stores media records:

- Media ID
- Album ID
- Original file name
- Server storage name
- Media type
- Upload time

### `upload_sessions`

Stores chunked-upload sessions:

- Upload session ID
- User ID
- Album ID
- Original file name
- Total file size
- Chunk size
- Total chunk count
- Upload status
- Creation and update time

## Pages and Basic Routes

| Method | Route | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/` | Public home page | Public |
| `GET, POST` | `/register` | Register an account | Public |
| `GET, POST` | `/login` | Sign in | Public |
| `POST` | `/logout` | Sign out | Signed-in users |
| `GET, POST` | `/change-password` | Change password | Signed-in users |
| `GET` | `/dashboard` | Personal album dashboard | Signed-in users |
| `GET, POST` | `/albums/create` | Create an album | Signed-in users |
| `GET` | `/albums/<album_id>` | View an album | Visibility-based access |
| `GET, POST` | `/albums/<album_id>/edit` | Rename an album | Album owner |
| `POST` | `/albums/<album_id>/visibility` | Toggle public or hidden through AJAX | Album owner |
| `POST` | `/albums/<album_id>/delete` | Delete an album through AJAX | Album owner |
| `POST` | `/albums/<album_id>/upload` | Standard multiple-file upload | Album owner |
| `GET` | `/media/<media_id>/file` | Read a media file | Visibility-based access |
| `POST` | `/media/<media_id>/delete` | Delete media through AJAX | Album owner |
| `GET` | `/users/<username>` | Public user profile | Public |
| `GET` | `/search?q=keyword` | Search users | Public |

## Chunked Upload Endpoints

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/albums/<album_id>/uploads/init` | Create or resume an upload session |
| `PUT` | `/uploads/<upload_id>/chunk` | Upload one file chunk |
| `POST` | `/uploads/<upload_id>/complete` | Validate and merge all chunks |

Chunked-upload flow:

1. The browser reads the file name, size, and required chunk count.
2. The initialization endpoint creates or resumes an upload session.
3. Chunks already stored by the server are skipped.
4. Remaining chunks are uploaded through AJAX.
5. The completion endpoint validates and merges all chunks.
6. The server stores the final file and inserts a record into `media`.
7. Duplicate display names receive an automatic numeric suffix.

## Supported File Types

Video:

```text
mp4, webm, ogg, mov, m4v
```

Image:

```text
png, jpg, jpeg, gif, webp
```

File types are filtered in the browser and validated again by the server. Files are stored under randomized server-side names while the original names remain visible in the interface.

## Access Rules

- Signed-out users can only view public albums and public profiles.
- Users can only modify or delete their own albums.
- Users can only upload files to their own albums.
- Users can only delete media from their own albums.
- Hidden albums are accessible only to their owners.
- Direct media URLs cannot bypass hidden-album permissions.
- All state-changing requests require a valid CSRF token.

## Project Structure

```text
flask-media-platform/
├── app.py                     # Flask application, routes, and business logic
├── server_app.py              # Direct startup entry point
├── requirements.txt           # Python dependencies
├── README.md                  # English documentation
├── README.zh.md               # Chinese documentation
├── templates/
│   ├── base.html              # Base page
│   ├── index.html             # Public home page
│   ├── register.html          # Registration page
│   ├── login.html             # Login page
│   ├── change_password.html   # Password change page
│   ├── dashboard.html         # Personal album dashboard
│   ├── album_form.html        # Album create and edit form
│   ├── album_detail.html      # Album details and upload area
│   ├── user_profile.html      # Public user profile
│   ├── search.html            # User search page
│   ├── error.html             # Error page
│   ├── _album_card.html       # Album card component
│   ├── _media_card.html       # Media card component
│   ├── _app_css.html          # Inline project CSS
│   ├── _bootstrap_css.html    # Inline Bootstrap CSS
│   ├── _bootstrap_js.html     # Inline Bootstrap JavaScript
│   ├── _uploader_js.html      # Inline chunked-upload JavaScript
│   └── _album_manager_js.html # Inline album-management JavaScript
├── uploads/                   # Completed media files
└── upload_chunks/             # Temporary incomplete chunks
```

The application automatically creates `app.db` and the required SQLite tables on first startup.

## Download, Install, and Run

```bash
git clone https://github.com/wangyifan349/flask-media-platform.git
cd flask-media-platform
pip install -r requirements.txt
python server_app.py
```

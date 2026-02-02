# EasyMyTicket Migration Guide (Using AWS S3)

This guide provides instructions to migrate your project and its database from your local machine to a cloud server using secure, encrypted S3 backups.

## 1. Local Configuration

1.  **AWS Setup**: Ensure you have an S3 bucket and an IAM user with programmatic access (Access Key ID and Secret Access Key).
2.  **Update `.env`**: Add the following variables to your local `backend/.env` file:
    ```bash
    AWS_ACCESS_KEY_ID=your_key
    AWS_SECRET_ACCESS_KEY=your_secret
    AWS_DEFAULT_REGION=your_region
    S3_BUCKET_NAME=your_bucket
    BACKUP_ENCRYPTION_KEY=your_master_passphrase
    ```
3.  **Take a Backup**: Run the backup script manually to upload your current data to S3:
    ```bash
    cd backend
    ./scripts/s3_backup.sh
    ```
    This will dump your database, encrypt it with AES-256, and upload it to `s3://your-bucket/backups/`.

---

## 2. Cloud Migration

1.  **Clone the Repo**: On your cloud server, clone the repository and navigate to the `backend` directory.
2.  **Setup Configuration**: Create a `.env` file on the cloud server. Use the **same** `BACKUP_ENCRYPTION_KEY` you used locally.
3.  **Start the Project**: Run the database startup script:
    ```bash
    chmod +x start_database.sh
    ./start_database.sh
    ```
    
    > [!NOTE]
    > The script will detect that the database is empty. It will automatically download the latest encrypted backup from S3, decrypt it using your passphrase, and import it into the new database.

---

## 3. Maintenance

- **Automatic Backups**: Every time you start the database via `./start_database.sh`, it takes a background backup and uploads it to S3.
- **Manual Backups**: You can run `./scripts/s3_backup.sh` at any time.
- **Scheduled Backups**: To take a backup every 6 hours, add this to your `crontab -e`:
  ```bash
  0 */6 * * * /path/to/backend/scripts/s3_backup.sh
  ```

## Security Note

- Your database data is **never** pushed to Git.
- It is **encrypted** before it leaves your machine.
- Your `BACKUP_ENCRYPTION_KEY` is your only way to restore your data. **Do not lose it.**

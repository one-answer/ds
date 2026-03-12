from dotenv import load_dotenv

import common


def main():
    load_dotenv()
    # common.init_db will prefer MySQL when MYSQL_* vars are configured.
    common.init_db("trading_logs.db")


if __name__ == "__main__":
    main()


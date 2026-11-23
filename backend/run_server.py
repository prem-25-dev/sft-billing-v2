import uvicorn
from app.main import app, parse_args

if __name__ == "__main__":
    args = parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
import argparse
import logging
from src.processors.email_processor import EmailProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Suppress DEBUG logs from underlying libraries
logging.getLogger('imap_client_lib').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(description='IMAP AI Assistant - AI-powered email to todo conversion')
    parser.add_argument('--test', action='store_true', help='Test all connections and configurations')
    parser.add_argument('--status', action='store_true', help='Show status summary')
    parser.add_argument('--responses', action='store_true', help='Process assignee responses')
    parser.add_argument('--config', default='settings.json', help='Path to configuration file')
    
    args = parser.parse_args()
    
    # Initialize the email processor
    processor = EmailProcessor(args.config)
    
    if args.test:
        # Test all connections
        logger.info("🔍 Testing all connections and configurations...")
        success = processor.test_connections()
        if success:
            logger.info("✅ All systems are ready!")
        else:
            logger.error("❌ Some systems have issues. Please check the logs.")
        return
    
    if args.status:
        # Show status summary
        status = processor.get_status_summary()
        logger.info("📊 System Status Summary:")
        for key, value in status.items():
            logger.info(f"  {key}: {value}")
        return
    
    if args.responses:
        # Process assignee responses
        logger.info("🔄 Processing assignee responses...")
        processor.process_assignee_responses()
        logger.info("✅ Response processing completed")
        return
    
    # Default action: process unread emails AND assignee responses
    logger.info("🚀 Starting IMAP AI Assistant")
    
    # Process regular emails first
    processor.process_unread_emails()
    logger.info("✅ Regular email processing completed")
    
    # Then process assignee responses
    logger.info("🔄 Processing assignee responses...")
    processor.process_assignee_responses()
    logger.info("✅ Response processing completed")
    
    logger.info("✅ All email processing completed")


if __name__ == "__main__":
    main()

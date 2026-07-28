const { publishToDevice } = require('./utils/mqttPublisher');

async function testPublish() {
  try {
    console.log('Publishing test setpoint to inhydro/system2/room1/setpoints/update...');
    await publishToDevice('inhydro/system2/room1/setpoints/update', {
      test: true,
      timestamp: new Date().toISOString(),
    });
    console.log('✅ Test publish succeeded!');
  } catch (err) {
    console.error('❌ Test publish failed:', err);
  }
}

testPublish();

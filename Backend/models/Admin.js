const mongoose = require('mongoose');
const bcrypt = require('bcryptjs');

const adminSchema = new mongoose.Schema(
	{
		name: {
			type: String,
			required: [true, 'Name is required'],
			trim: true,
			maxlength: [50, 'Name cannot exceed 50 characters'],
		},
		email: {
			type: String,
			required: [true, 'Email is required'],
			unique: true,
			lowercase: true,
			trim: true,
			match: [/^\S+@\S+\.\S+$/, 'Please provide a valid email'],
		},
		password: {
			type: String,
			required: [true, 'Password is required'],
			minlength: [6, 'Password must be at least 6 characters'],
			select: false,
		},
		role: {
			type: String,
			enum: ['admin', 'superadmin'],
			default: 'admin',
		},
		isActive: {
			type: Boolean,
			default: true,
		},
		lastLogin: {
			type: Date,
		},
		permissions: {
			type: [String],
			default: ['all'],
		},
		assignedLocations: {
			type: [String],
			default: [],
		},
		assignedDevices: [
			{
				type: mongoose.Schema.Types.ObjectId,
				ref: 'Device',
			},
		],
		resetPasswordOtp: {
			type: String,
		},
		resetPasswordExpires: {
			type: Date,
		},
	},
	{
		timestamps: true,
		collection: 'admins',
	}
);

adminSchema.pre('save', async function () {
	if (!this.isModified('password')) return;
	const salt = await bcrypt.genSalt(12);
	this.password = await bcrypt.hash(this.password, salt);
});

adminSchema.methods.comparePassword = async function (candidatePassword) {
	return bcrypt.compare(candidatePassword, this.password);
};

module.exports = mongoose.model('Admin', adminSchema);
